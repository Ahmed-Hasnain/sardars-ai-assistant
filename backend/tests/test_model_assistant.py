"""The prototype always reaches the model while data access stays in application code."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone

from app.llm.base import ChatResult, ModelToolCall, ToolChatResult
from app.rag.answer_seed import Evidence
from app.schemas.chat import ChatResponse
from app.services.model_assistant import _sources, answer_model_first
from app.tools.schemas import ProductCategoryResults, ToolSuccess


def _model(text="Hello!"):
    model = SimpleNamespace()
    model.chat = AsyncMock(return_value=ChatResult(text, "test-model", 10, 5, 20))
    model.chat_with_tools = AsyncMock(return_value=ToolChatResult(text, "test-model", (), 10, 5, 20))
    return model


def _decision(*calls, text=""):
    return ToolChatResult(text, "test-model", calls, 10, 5, 20)


def test_greeting_reaches_plain_model_without_evidence():
    model = _model("I'm well, thanks. How can I help?")
    with patch("app.services.model_assistant._authorized_excerpts", new_callable=AsyncMock, return_value=[]):
        result = asyncio.run(answer_model_first("hello how are you", SimpleNamespace(role="staff"), None, model))
    assert result.answer.startswith("I'm well")
    assert result.route == "general"
    model.chat.assert_awaited_once()
    model.chat_with_tools.assert_not_awaited()


def test_company_question_uses_authorized_evidence_and_maps_citation():
    evidence = Evidence("a" * 64, "About us", "https://sardarandco.com/pages/about-us", None,
                        "Sardars sells bathroom fittings.")
    model = _model("Sardars sells bathroom fittings. [1]")
    with patch("app.services.model_assistant._authorized_excerpts", new_callable=AsyncMock, return_value=[evidence]):
        result = asyncio.run(answer_model_first("What is Sardars?", SimpleNamespace(role="staff"), None, model))
    assert "Sardars sells bathroom fittings." in result.answer
    assert result.sources[0].source_id == "a" * 64
    assert "Sardars sells bathroom fittings." in model.chat.await_args.args[0][-2]["content"]


def test_company_identity_uses_its_actual_about_passage_when_model_hallucinates():
    evidence = Evidence("a" * 64, "About Us", "https://sardarandco.com/pages/about-us", None,
                        "Our team specializes in providing luxury sanitary products to customers.")
    model = _model("Sardars is a shoemaker. [1]")
    with patch("app.services.model_assistant._authorized_excerpts", new_callable=AsyncMock,
               return_value=[evidence]):
        result = asyncio.run(answer_model_first("What is Sardars?", SimpleNamespace(role="staff"), None, model))
    assert "luxury sanitary products" in result.answer
    assert "shoemaker" not in result.answer
    assert result.sources[0].source_id == evidence.source_id
    model.chat.assert_awaited_once()
    model.chat_with_tools.assert_not_awaited()


def test_customer_opinion_uses_exact_qualified_faq_without_source_metadata_echo():
    evidence = Evidence(
        "b" * 64, "Sardars Customer Q and A", "/api/v1/ingestion/files/faq-id", None,
        "SARDARS-FAQ-236 | What do customers say about Sardars? "
        "Answer: The inspected directory sample includes praise for variety and staff, alongside price criticism. "
        "This is a limited platform-specific sample. Question origin: anticipated_customer_question",
    )
    model = _model("Question origin: anticipated_customer_question. Everyone loves Sardars. [1]")
    with patch("app.services.model_assistant._authorized_excerpts", new_callable=AsyncMock,
               return_value=[evidence]):
        result = asyncio.run(answer_model_first(
            "What do customers say about Sardars?", SimpleNamespace(role="staff"), None, model,
        ))
    assert "price criticism" in result.answer
    assert "limited platform-specific sample" in result.answer
    assert "Question origin" not in result.answer
    assert "Everyone loves" not in result.answer
    assert result.sources[0].source_id == evidence.source_id
    model.chat.assert_awaited_once()
    model.chat_with_tools.assert_not_awaited()


def test_missing_retrieval_still_reaches_model():
    model = _model("I can explain the general options, but I have no Sardars source for this detail.")
    with patch("app.services.model_assistant._authorized_excerpts", new_callable=AsyncMock, return_value=[]):
        result = asyncio.run(answer_model_first("What are Sardars' competitors?", SimpleNamespace(role="staff"), None, model))
    assert result.model == "test-model"
    assert "general options" in result.answer
    model.chat_with_tools.assert_awaited_once()


def test_model_followup_search_is_bounded_and_final_answer_gets_evidence():
    model = _model("Sardars has a Rawalpindi showroom. [1]")
    model.chat_with_tools.return_value = _decision(ModelToolCall("search_company_sources", {"query": "Sardars showroom"}))
    evidence = Evidence("b" * 64, "Contact", "https://sardarandco.com/pages/contact", None,
                        "Sardars has a Rawalpindi showroom.")
    search = AsyncMock(side_effect=[[], [evidence]])
    with patch("app.services.model_assistant._authorized_excerpts", search):
        result = asyncio.run(answer_model_first("Where is the showroom?", SimpleNamespace(role="staff"), None, model))
    assert search.await_count == 2
    assert result.sources[0].source_id == "b" * 64
    assert "Rawalpindi showroom" in model.chat.await_args.args[0][1]["content"]


def test_followup_evidence_displaces_lower_priority_initial_excerpt():
    model = _model("A cited answer. [1]")
    model.chat_with_tools.return_value = _decision(ModelToolCall("search_company_sources", {"query": "specific answer"}))
    initial = [Evidence(str(i) * 64, f"Old {i}", "https://sardarandco.com/pages/about-us", None,
                        f"Unrelated passage {i}.") for i in range(1, 4)]
    fresh = Evidence("f" * 64, "Relevant", "https://sardarandco.com/pages/about-us", None,
                     "The specific answer is here.")
    with patch("app.services.model_assistant._authorized_excerpts", new_callable=AsyncMock,
               side_effect=[initial, [fresh]]):
        result = asyncio.run(answer_model_first("What is the specific answer?", SimpleNamespace(role="staff"), None, model))
    assert result.sources[0].source_id == fresh.source_id
    assert "The specific answer is here." in model.chat.await_args.args[0][-2]["content"]
    assert "Unrelated passage 3" not in model.chat.await_args.args[0][-2]["content"]


def test_bad_tool_arguments_never_execute():
    model = _model("I can help you find a product.")
    model.chat_with_tools.return_value = _decision(ModelToolCall("search_company_sources", {"query": "a"}))
    with patch("app.services.model_assistant._authorized_excerpts", new_callable=AsyncMock, return_value=[]) as search:
        asyncio.run(answer_model_first("What is Sardars?", SimpleNamespace(role="staff"), None, model))
    search.assert_awaited_once()


def test_product_request_reaches_model_and_uses_database_result():
    model = _model("I found a matching product.")
    product = ChatResponse(answer="Bongio tap: SKU B-1, price 123, database stock 2.",
                           route="product_search", model=None, company_data_verified=True)
    with patch("app.services.model_assistant._authorized_excerpts", new_callable=AsyncMock, return_value=[]), \
         patch("app.services.model_assistant.answer_product_discovery", new_callable=AsyncMock, return_value=product) as lookup:
        result = asyncio.run(answer_model_first("Give me some products of Bongio", SimpleNamespace(role="staff"), None, model))
    assert "Bongio tap: SKU B-1" in result.answer
    assert result.company_data_verified is True
    lookup.assert_awaited_once()
    model.chat.assert_awaited_once()
    model.chat_with_tools.assert_not_awaited()
    assert "Authorized PostgreSQL lookup result" in model.chat.await_args.args[0][-2]["content"]


def test_bare_sku_uses_exact_catalog_even_when_rag_excerpt_mentions_it():
    model = _model("This SKU belongs to a different company and costs 999.")
    evidence = Evidence("a" * 64, "General KB", "https://example.test/kb", None,
                        "The KB mentions product IDs but has no TEST-1701 details.")
    product = ChatResponse(answer="Acqua fan; SKU TEST-1701, price 124; catalog category: Fans.",
                           route="product", model=None, company_data_verified=True,
                           product_handles=["1689"])
    with patch("app.services.model_assistant._authorized_excerpts", new_callable=AsyncMock, return_value=[evidence]), \
         patch("app.services.model_assistant.answer_product", new_callable=AsyncMock, return_value=product) as lookup:
        result = asyncio.run(answer_model_first(
            "Give complete information about product TEST-1701", SimpleNamespace(role="staff"), None, model,
        ))
    lookup.assert_awaited_once()
    assert result.answer == product.answer
    assert result.product_handles == ["1689"]
    assert "different company" not in result.answer
    model.chat_with_tools.assert_not_awaited()
    model.chat.assert_awaited_once()


def test_single_product_category_followup_uses_prior_handle():
    model = _model("It is a basin.")
    product = ChatResponse(answer="Catalog category: Fans.", route="product", model=None,
                           company_data_verified=True, product_handles=["1689"])
    with patch("app.services.model_assistant._authorized_excerpts", new_callable=AsyncMock, return_value=[]), \
         patch("app.services.model_assistant.answer_product", new_callable=AsyncMock, return_value=product) as lookup, \
         patch("app.services.model_assistant.answer_product_discovery", new_callable=AsyncMock) as browse:
        result = asyncio.run(answer_model_first(
            "What is the category of this product?", SimpleNamespace(role="staff"), None, model,
            product_handles=["1689"], previous_question="Show SKU TEST-1701",
        ))
    assert result.answer == "Catalog category: Fans."
    assert lookup.await_args.kwargs["identifier"] == "1689"
    browse.assert_not_called()


def test_natural_fan_question_and_price_options_use_catalog_browse():
    for question in ("Give me some fans", "Does Sardars offer fans?", "Product options under 10000"):
        model = _model("Sardars has fans in New York and London.")
        product = ChatResponse(answer="Matching authorized catalog products.",
                               route="product_search", model=None, company_data_verified=True)
        with patch("app.services.model_assistant._authorized_excerpts", new_callable=AsyncMock, return_value=[]), \
             patch("app.services.model_assistant.answer_product_discovery", new_callable=AsyncMock,
                   return_value=product) as browse:
            result = asyncio.run(answer_model_first(question, SimpleNamespace(role="staff"), None, model))
        browse.assert_awaited_once()
        model.chat_with_tools.assert_not_awaited()
        model.chat.assert_awaited_once()
        assert result.answer == product.answer
        assert "New York" not in result.answer


def test_repeated_source_excerpts_have_one_contiguous_citation_number():
    first = Evidence("a" * 64, "FAQ", "https://example.test/faq", None, "First fact")
    second = Evidence("b" * 64, "About", "https://example.test/about", None, "Second fact")
    text, citations = _sources("First [3] and another [1], second [2]; invalid [9].", [first, second, first])
    assert text == "First [1] and another [1], second [2]; invalid ."
    assert [(item.number, item.source_id) for item in citations] == [(1, "a" * 64), (2, "b" * 64)]


def test_model_product_tool_call_is_executed_through_application_lookup():
    model = _model("Here are the results.")
    model.chat_with_tools.return_value = _decision(ModelToolCall("search_products", {"question": "Bongio products"}))
    product = ChatResponse(answer="Bongio: SKU B-2, price 45.", route="product_search", model=None)
    with patch("app.services.model_assistant._authorized_excerpts", new_callable=AsyncMock, return_value=[]), \
         patch("app.services.model_assistant.answer_product_discovery", new_callable=AsyncMock, return_value=product) as lookup:
        result = asyncio.run(answer_model_first("What is Bongio?", SimpleNamespace(role="staff"), None, model))
    assert "SKU B-2" in result.answer
    lookup.assert_awaited_once()


def test_category_question_reaches_model_but_returns_visible_catalog_labels():
    model = _model("The categories are [P004, P005].")
    model.chat_with_tools.return_value = _decision(ModelToolCall("search_products", {"question": "product categories"}))
    evidence = Evidence("c" * 64, "Company range", "https://sardarandco.com/pages/about-us", None,
                        "The range includes sanitaryware, taps and showers.")
    categories = ProductCategoryResults(observed_at=datetime.now(timezone.utc),
                                         categories=["Sanitary Fittings", "Tiles"],
                                         source_file_sha256=["a" * 64])
    with patch("app.services.model_assistant._authorized_excerpts", new_callable=AsyncMock, return_value=[evidence]), \
         patch("app.services.model_assistant.answer_product_discovery", new_callable=AsyncMock) as lookup, \
         patch("app.services.model_assistant.execute_tool", return_value=ToolSuccess(
             tool="list_product_categories", data=categories)) as tool:
        result = asyncio.run(answer_model_first("What are the categories of the products?",
                                                SimpleNamespace(role="staff"), None, model))
    assert result.route == "product_search"
    assert "Sanitary Fittings, Tiles" in result.answer
    assert "P004" not in result.answer
    lookup.assert_not_called()
    tool.assert_called_once()
    model.chat.assert_awaited_once()


