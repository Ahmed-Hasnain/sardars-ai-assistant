"""The baseline must detect wrong facts, wrong tools and unavailable services."""

import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import chat
from app.db.base import Base
from app.db.products import Product
from app.evaluation.observe_chat import Observation
from app.evaluation.run_chat import (
    CASES_PATH, ChatCase, check_response, evaluate, load_cases, run, summarize,
)
from app.llm.base import ChatResult, ModelError, ToolChatResult
from app.rag.answer_seed import FALLBACK
from app.schemas.ask import SourceCitation
from app.schemas.chat import ChatResponse
from app.services import model_assistant, product_discovery


def _model():
    model = AsyncMock()
    model.chat.return_value = ChatResult("I cannot verify that detail from available sources.", "fixture", 10, 5, 20)
    model.chat_with_tools.return_value = ToolChatResult("", "fixture", (), 10, 0, 20)
    return model


@pytest.fixture(autouse=True)
def no_live_index(monkeypatch):
    monkeypatch.setattr(model_assistant, "search_for_role", lambda *_: [])
    monkeypatch.setattr(product_discovery, "fetch_product_points", lambda *_: [])


@pytest.fixture
def sessions():
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory.begin() as db:
        db.add(Product(source_file_name="fixture.csv", source_file_sha256="a" * 64,
                       source_row_number=1, handle="test-basin", title="Test Basin Mixer",
                       variant_sku="TEST-1", variant_price=125, variant_inventory_qty=6, status="active",
                       source_row_kind="variant", visibility="staff"))
    yield factory
    engine.dispose()


def case(**overrides):
    return ChatCase.model_validate(dict(id="test_case", category="exact_facts",
        question="What is the price for SKU TEST-1?", expected_source=None,
        expected_route="product", expected_tools=["get_product_details"], expected_sku="TEST-1") | overrides)


def test_case_file_has_live_categories_and_isolated_controls():
    cases = load_cases(CASES_PATH)
    assert len(cases) == 26
    assert sum(bool(c.control) for c in cases) == 8
    assert {c.expected_route for c in cases} == {"company", "general", "product", "product_search", "out_of_scope"}


@pytest.mark.parametrize("data", [[], [{"id": "bad"}], [{}] * 61])
def test_invalid_cases_are_rejected(tmp_path, data):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_cases(path)


def test_duplicate_oversized_and_conflicting_cases_are_rejected(tmp_path):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps([case().model_dump()] * 2))
    with pytest.raises(ValueError):
        load_cases(path)
    path.write_bytes(b" " * (64 * 1024 + 1))
    with pytest.raises(ValueError):
        load_cases(path)
    with pytest.raises(ValueError):
        case(abstain=True, expected_source="https://sardarandco.com/pages/about-us")


def test_live_tool_is_observed_and_facts_are_checked_independently(sessions):
    model = _model()
    row = asyncio.run(evaluate(case(), model, sessions))
    assert row["passed"]
    assert row["checks"]["exact_facts"] is True
    assert [call["name"] for call in row["observation"]["tools"]] == ["get_product_details"]
    assert len(row["observation"]["model_calls"]) == 1
    assert not row["observation"]["model_calls"][0].get("tool_choice", False)
    model.chat.assert_awaited_once()
    response = ChatResponse.model_validate(row["response"])
    with sessions() as db:
        for wrong in ("12", "1250", "999"):
            forged = response.model_copy(update={"answer": response.answer.replace("price 125", f"price {wrong}")})
            assert check_response(case(), forged, Observation(), db)["exact_facts"] is False
    # The CLI uses the answer dispatcher, so no conversations or accounts exist.
    from sqlalchemy import func, select
    from app.db.models import Conversation, User
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(Conversation)) == 0
        assert db.scalar(select(func.count()).select_from(User)) == 0


def test_expected_tool_is_not_inferred_from_a_matching_route(sessions):
    c = case(expected_tools=["search_products"])
    row = asyncio.run(evaluate(c, _model(), sessions))
    assert not row["passed"] and row["checks"]["routing"] is True
    assert row["checks"]["tool_selection"] is False


def test_stock_checker_catches_wrong_quantity_and_tracks_zero(sessions):
    c = case(expected_stock_sku="TEST-1")
    row = asyncio.run(evaluate(c, _model(), sessions))
    assert row["passed"] and row["checks"]["stock_facts"] is True
    response = ChatResponse.model_validate(row["response"])
    forged = response.model_copy(update={"answer": response.answer.replace("stock 6 units", "stock 9 units")})
    with sessions() as db:
        assert check_response(c, forged, Observation(), db)["stock_facts"] is False
    with sessions.begin() as db:
        db.query(Product).filter(Product.variant_sku == "TEST-1").update({"variant_inventory_qty": 0})
    zero = asyncio.run(evaluate(c, _model(), sessions))
    assert zero["passed"] and "database stock 0 units" in zero["response"]["answer"]


def test_general_answer_records_context_counts_without_prompt_text(sessions):
    model = _model()
    model.chat.return_value = ChatResult("It controls temperature.", "fixture", 12, 4, 10)
    c = case(category="technical", question="What is a mixer?", expected_route="general",
             expected_tools=[], expected_sku=None, answer_contains=["temperature"])
    original = chat.chat_model
    row = asyncio.run(evaluate(c, model, sessions))
    assert row["passed"] and chat.chat_model is original
    assert row["observation"]["model_calls"][0]["tool_choice"] is True
    metrics = row["observation"]["model_calls"][-1]
    assert metrics["prompt_tokens"] == 12 and metrics["output_tokens"] == 4
    assert metrics["context_characters"] > len(c.question)
    assert "content" not in metrics and "messages" not in metrics


def test_general_answer_requires_bathroom_context_not_just_temperature(sessions):
    model = _model()
    model.chat.return_value = ChatResult("A food mixer controls the temperature of ingredients.", "fixture", 12, 10, 15)
    c = case(category="technical", question="What is a bathroom tap mixer?", expected_route="general",
             expected_tools=[], expected_sku=None, answer_contains=["water", "temperature"],
             answer_not_contains=["food", "ingredients"])
    row = asyncio.run(evaluate(c, model, sessions))
    assert row["checks"]["answer"] is False and not row["passed"]
    model.chat.return_value = ChatResult("It adjusts water temperature for a bathroom heating system.",
                                         "fixture", 12, 10, 15)
    c = c.model_copy(update={"answer_contains_any": ["shower", "tap", "bathroom fixture"],
                             "answer_not_contains": ["heating system"]})
    row = asyncio.run(evaluate(c, model, sessions))
    assert row["checks"]["answer"] is False and not row["passed"]


def test_model_failure_is_failed_and_private_error_is_not_recorded(sessions):
    model = _model()
    model.chat.side_effect = ModelError("PRIVATE_ERROR")
    c = case(question="What is a mixer?", expected_route="general", expected_tools=[], expected_sku=None)
    row = asyncio.run(evaluate(c, model, sessions))
    assert not row["passed"] and row["checks"]["service"] is False
    assert "PRIVATE_ERROR" not in str(row)


def test_retrieval_failure_does_not_pass_a_missing_policy(sessions, monkeypatch):
    def unavailable(*args):
        raise httpx.ConnectError("PRIVATE_ERROR")
    monkeypatch.setattr(model_assistant, "search_for_role", unavailable)
    c = case(question="What is Sardars' return policy?", expected_route="company",
             expected_tools=[], expected_sku=None, abstain=True)
    row = asyncio.run(evaluate(c, _model(), sessions))
    assert not row["passed"] and row["checks"]["service"] is False
    assert "PRIVATE_ERROR" not in str(row)


def test_swallowed_description_outage_is_reported_separately(sessions, monkeypatch):
    def unavailable(*args):
        raise httpx.ConnectError("PRIVATE_ERROR")
    monkeypatch.setattr(product_discovery, "fetch_product_points", unavailable)
    c = case(question="Show me basin mixers", expected_route="product_search",
             expected_tools=["search_products"], expected_sku=None, min_products=1)
    row = asyncio.run(evaluate(c, _model(), sessions))
    assert not row["passed"]
    assert row["checks"]["exact_facts"] is True and row["checks"]["service"] is False
    assert "PRIVATE_ERROR" not in str(row)


def test_continuation_variant_uses_active_parent_and_checks_rendered_values(sessions, monkeypatch):
    monkeypatch.setattr(product_discovery, "fetch_product_points", lambda *args: [])
    with sessions.begin() as db:
        db.add(Product(source_file_name="fixture.csv", source_file_sha256="a" * 64,
                       source_row_number=2, handle="test-basin", variant_sku="TEST-2",
                       variant_price=100, status=None, source_row_kind="variant", visibility="staff"))
    c = case(question="Compare SKU TEST-1 and SKU TEST-2", expected_route="product_search",
             expected_tools=["search_products"], expected_sku=None, min_products=2)
    row = asyncio.run(evaluate(c, _model(), sessions))
    assert row["passed"] and row["checks"]["exact_facts"] is True
    response = ChatResponse.model_validate(row["response"])
    forged = response.model_copy(update={"answer": response.answer.replace("price 100", "price 999")})
    with sessions() as db:
        assert check_response(c, forged, Observation(), db)["exact_facts"] is False


def test_combined_answer_needs_a_description_for_its_actual_product(sessions, monkeypatch):
    monkeypatch.setattr(product_discovery, "fetch_product_points", lambda *args: [])
    c = case(question="Show me basin mixers under 1000", expected_route="product_search",
             expected_tools=["search_products"], expected_sku=None, min_products=1,
             min_citations=1, price_under=1000)
    row = asyncio.run(evaluate(c, _model(), sessions))
    assert row["checks"]["description_join"] is False and not row["passed"]
    assert row["checks"]["price_filter"] is True


def test_forged_citations_and_source_misses_are_distinct(sessions):
    url = "https://sardarandco.com/pages/about-us"
    c = case(expected_route="company", expected_tools=[], expected_sku=None, expected_source=url)
    response = ChatResponse(answer="Sardars [2]", route="company", model=None,
        sources=[SourceCitation(number=1, source_id="a" * 64, title="About", url=url, fetched_at=None)])
    with sessions() as db:
        checks = check_response(c, response, Observation(), db)
    assert checks["expected_source"] is True
    assert checks["retrieval"] is False and checks["citations"] is False


@pytest.mark.parametrize("c", [c for c in load_cases(CASES_PATH) if c.control], ids=lambda c: c.id)
def test_disposable_controls_never_open_project_sessions(c):
    def forbidden():
        raise AssertionError("Live database must not be used by controls")
    row = asyncio.run(evaluate(c, _model(), forbidden))
    assert row["passed"] and row["mode"] == "synthetic_control"


def test_summary_separates_controls_latency_and_unmeasured_checks():
    rows = [{"mode": "live_service", "passed": True, "checks": {"retrieval": True},
             "total_ms": 10, "observation": {"model_calls": []}},
            {"mode": "live_service", "passed": False, "checks": {"service": False},
             "total_ms": 30, "observation": {"model_calls": []}},
            {"mode": "synthetic_control", "passed": True, "checks": {"isolated_trust_control": True}, "total_ms": 999}]
    summary = summarize(rows)
    assert summary["live_latency_median_ms"] == 20 and summary["live_latency_p95_ms"] == 30
    assert summary["checks"]["retrieval"] == {"measured": 1, "passed": 1}
    assert summary["by_mode"]["live_service"] == {"cases": 2, "passed": 1}


def test_existing_report_is_preserved_before_evaluation(tmp_path):
    from types import SimpleNamespace
    path = tmp_path / "baseline.json"
    path.write_text("previous evidence")
    with pytest.raises(FileExistsError):
        asyncio.run(run(SimpleNamespace(cases=CASES_PATH, report=path)))
    assert path.read_text() == "previous evidence"
