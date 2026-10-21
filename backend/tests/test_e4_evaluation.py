"""Ensure the E4 measurements distinguish failures and preserve search budgets."""

import pytest

from app.evaluation import run_e4
from app.evaluation.e4_inventory import distribution, faq_audit, scan_points
from app.evaluation.run_chat import load_cases
from app.core.config import Settings


def test_ablation_excludes_uploads_inside_query_before_ranking(monkeypatch):
    calls = []
    monkeypatch.setattr(run_e4, "_query", lambda *args: calls.append(args) or [])
    run_e4.make_search(["a" * 64])("Who are Sardars?", "staff")
    question, conditions, visibility = calls[0]
    assert question == "Who are Sardars?"
    assert visibility == {"public", "staff"}
    assert conditions[-1] == {"must_not": [{"key": "source_id", "match": {"any": ["a" * 64]}}]}
    assert run_e4.make_search(["a" * 64])("question", "invalid") == []
    assert len(calls) == 1


@pytest.mark.parametrize(("failures", "stages", "expected"), [
    ([], [], []),
    (["routing", "answer"], [], ["routing"]),
    (["retrieval", "expected_source"], [], ["retrieval"]),
    (["service"], [], ["service"]),
    (["citations"], [], ["citation_provenance"]),
    (["expected_source"], [], ["citation_identity_review"]),
    (["answer"], [{"matching_sentences": 0, "exact_faq_answer": False}], ["evidence_selection"]),
    (["answer"], [{"matching_sentences": 1, "exact_faq_answer": False}], ["answer_generation_or_support_review"]),
])
def test_diagnostics_do_not_treat_source_mismatch_as_hallucination(failures, stages, expected):
    assert run_e4.diagnose({"failures": failures}, stages) == expected


def test_latency_distribution_uses_median_and_nearest_rank_p95():
    assert distribution([1, 3, 5, 99]) == {"count": 4, "median": 4, "p95": 99}
    assert distribution([]) == {"count": 0, "median": None, "p95": None}


def test_e4_cases_cover_every_upload_and_both_roles():
    cases = load_cases(run_e4.CASES_PATH)
    assert len(cases) == 21
    assert {case.role for case in cases} == {"staff", "admin"}
    assert len({case.expected_source for case in cases
                if case.expected_source and case.expected_source.startswith("/api/")}) == 3
    assert sum(case.abstain for case in cases) == 6


def test_faq_audit_distinguishes_question_guards_and_partial_answer_candidates():
    from hashlib import sha256
    url = "/api/v1/ingestion/files/24716db5-f918-4512-b49d-0c035f1f13b3"
    full = ("SARDARS-FAQ-001 | What is Sardars?\n"
            "Answer: Sardars supplies bathroom fittings. Check each model separately.\n"
            "Question origin: anticipated\n\n"
            "SARDARS-FAQ-002 | What is the price?\n"
            "Answer: Please ask the team to confirm the details.\n"
            "Question origin: anticipated")
    payload = {"url": url, "source_id": sha256(url.encode()).hexdigest(),
               "visibility": "staff", "source_type": "text", "review_status": "approved",
               "prototype_only": False, "title": "FAQ", "text": full}
    audit = faq_audit({"text": full}, [{"payload": payload}])
    assert audit == {"pairs": 2, "full_answer_guard_eligible": 2,
                     "question_and_answer_guard_eligible": 1,
                     "indexed_answer_candidates": 2, "partial_answer_questions": []}
    partial = payload | {"text": "SARDARS-FAQ-001 | What is Sardars? Answer: Sardars supplies bathroom fittings."}
    audit = faq_audit({"text": full}, [{"payload": partial}])
    assert audit["partial_answer_questions"] == ["What is Sardars?"]
    assert faq_audit({"text": "Ordinary text"}, []) is None


def test_inventory_rejects_nonadvancing_scroll(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"result": {"points": [{"payload": {}}], "next_page_offset": "same"}}

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr("app.evaluation.e4_inventory.httpx.Client", Client)
    with pytest.raises(ValueError, match="did not advance"):
        scan_points(Settings())
