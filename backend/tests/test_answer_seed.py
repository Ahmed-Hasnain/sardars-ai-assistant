import asyncio
from unittest.mock import AsyncMock

from app.llm.base import ChatResult
from app.rag.answer_seed import FALLBACK, answer_from_points


def _point() -> dict:
    return {
        "payload": {
            "visibility": "public",
            "review_status": "approved",
            "prototype_only": False,
            "source_type": "pages",
            "title": "About Us",
            "url": "https://sardarandco.com/pages/about-us",
            "text": "Sardars mentions brands like Bongio, Scarabeo and Grohe.",
        }
    }


def test_answer_cites_the_used_source() -> None:
    model = AsyncMock()
    model.chat.return_value = ChatResult(
        "Sardars mentions Bongio, Scarabeo and Grohe. [1]", "test-model", None, None, None
    )

    result = asyncio.run(answer_from_points("Which brands?", [_point()], model))

    assert result.sources == [("About Us", "https://sardarandco.com/pages/about-us")]
    assert "[1]" in result.text
    assert "Source excerpts:" in model.chat.await_args.args[0][1]["content"]


def test_no_approved_evidence_does_not_call_model() -> None:
    point = _point()
    point["payload"]["review_status"] = "pending"
    model = AsyncMock()

    result = asyncio.run(answer_from_points("What is the return policy?", [point], model))

    assert result.text == FALLBACK
    assert result.sources == []
    model.chat.assert_not_called()


def test_missing_policy_evidence_does_not_inherit_an_unrelated_citation() -> None:
    model = AsyncMock()

    result = asyncio.run(answer_from_points("What is the return policy?", [_point()], model))

    assert result.text == FALLBACK
    assert result.sources == []
    model.chat.assert_not_called()


def test_model_fallback_does_not_hide_matching_brand_evidence() -> None:
    model = AsyncMock()
    model.chat.return_value = ChatResult(FALLBACK, "test-model", None, None, None)

    result = asyncio.run(answer_from_points("Which brands does Sardars mention?", [_point()], model))

    assert "Bongio, Scarabeo and Grohe" in result.text
    assert result.sources == [("About Us", "https://sardarandco.com/pages/about-us")]


def test_unknown_citation_falls_back_to_the_exact_source_sentence() -> None:
    model = AsyncMock()
    model.chat.return_value = ChatResult(
        "The brands include an invented name. [7]", "test-model", None, None, None
    )

    result = asyncio.run(answer_from_points("Which brands?", [_point()], model))

    assert result.text == "Sardars mentions brands like Bongio, Scarabeo and Grohe. [1]"
    assert result.sources == [("About Us", "https://sardarandco.com/pages/about-us")]


def test_citation_does_not_allow_an_invented_claim() -> None:
    model = AsyncMock()
    model.chat.return_value = ChatResult(
        "Sardars mentions an exclusive 30-day brand warranty. [1]",
        "test-model", None, None, None,
    )

    result = asyncio.run(answer_from_points("Which brands?", [_point()], model))

    assert result.text == "Sardars mentions brands like Bongio, Scarabeo and Grohe. [1]"
