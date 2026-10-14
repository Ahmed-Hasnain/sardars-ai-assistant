"""Evaluation failures stay failures; controls do not modify the live corpus."""

import asyncio
from unittest.mock import AsyncMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.evaluation.run_coverage import Case, CONTROL_URL, control_points, evaluate, summarize, validate_answer
from app.llm.base import ChatResult
from app.rag.answer_seed import CitedAnswer, CitedSource, FALLBACK, answer_from_points


def case(control="admin_hidden", **kwargs):
    return Case(id=control, question="What is Controlbrand?", expected_source=None, control=control, **kwargs)


def test_synthetic_permission_and_generation_controls_exclude_unsafe_sources():
    for control in ["admin_hidden", "unregistered", "disabled", "failed", "stale_generation"]:
        assert control_points(case(control)) == []
    assert control_points(case("admin_visible", role="admin"))


def test_control_injection_conflicts_and_visible_admin_are_checked_through_answer_path():
    for control, question in [("injection", "What is Controlbrand?"), ("conflict", "Does the warranty include installation?")]:
        c = Case(id=control, question=question, control=control, expected_source=None)
        model = AsyncMock()
        row = asyncio.run(evaluate(c, model))
        assert row["passed"] and row["mode"] == "synthetic_control"
        model.chat.assert_not_called()
    c = Case(id="admin_visible", question="What is Controlbrand?", control="admin_visible", role="admin", expected_source=CONTROL_URL, answer_contains=["Controlbrand", "brand"])
    assert asyncio.run(evaluate(c, AsyncMock()))["passed"]


def test_evaluation_catches_forged_or_mismatched_citations():
    c = case()
    result = CitedAnswer("Invented answer [2]", [CitedSource(1, "a" * 64, "Other", "https://other.test/", None)])
    failures = validate_answer(c, result, [])
    assert "citation is outside the authorized retrieved evidence" in failures
    assert "citation markers do not match returned sources" in failures


def test_live_service_failure_cannot_pass_an_abstention_case():
    import httpx
    def search(*args):
        raise httpx.ConnectError("PRIVATE_SERVICE_DETAIL")
    c = Case(id="missing_policy", question="What is Sardars' return policy?", expected_source=None)
    row = asyncio.run(evaluate(c, AsyncMock(), search=search))
    assert not row["passed"] and "PRIVATE" not in str(row)


def test_latency_summary_separates_live_measurements_from_controls():
    rows = [{"mode":"live","passed":True,"retrieval_hit":True,"total_ms":10},
            {"mode":"live","passed":False,"retrieval_hit":False,"total_ms":30},
            {"mode":"synthetic_control","passed":True,"total_ms":1}]
    summary = summarize(rows)
    assert summary["supported_retrieval_hits"] == 1 and summary["supported_retrieval_cases"] == 2
    assert summary["live_latency_median_ms"] == 20 and summary["live_latency_p95_ms"] == 30


def test_general_education_control_only_measures_routing():
    c = Case(id="general", question="Explain what a database is.", expected_source=None, control="routing_general")
    row = asyncio.run(evaluate(c, AsyncMock()))
    assert row["passed"] and row["mode"] == "routing_only"
