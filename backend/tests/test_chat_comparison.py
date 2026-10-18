"""Saved reports must never turn changed cases/data into claimed improvements."""

import json

import pytest

from app.evaluation.compare_chat import compare, load_report


def report(passed: bool, *, case=None, fingerprint="fixed"):
    definition = case or {"id": "stock", "question": "Stock for SKU TEST-1?", "expected_route": "product"}
    return {
        "metadata": {"protocol_version": 3, "evaluator_sha256": "evaluator", "chat_model": "local",
                     "embedding_model": "embed", "collection": "index",
                     "data_fingerprint_before": fingerprint, "data_fingerprint_after": fingerprint},
        "summary": {"data_stable_during_run": True},
        "case_definitions": [definition],
        "cases": [{"id": definition["id"], "passed": passed}],
    }


def test_controlled_comparison_identifies_a_gain_and_regression():
    result = compare(report(False), report(True))
    assert result["controlled_comparison"]
    assert result["improved_case_ids"] == ["stock"]
    assert result["regressed_case_ids"] == []
    reverse = compare(report(True), report(False))
    assert reverse["regressed_case_ids"] == ["stock"]


def test_changed_case_or_data_cannot_be_claimed_as_controlled_gain():
    changed_case = report(True, case={"id": "stock", "question": "Different question", "expected_route": "product"})
    result = compare(report(False), changed_case)
    assert not result["controlled_comparison"]
    assert result["changed_case_ids"] == ["stock"] and result["improved_case_ids"] == []
    changed_data = compare(report(False), report(True, fingerprint="different"))
    assert not changed_data["controlled_comparison"]
    changed_data = compare(report(False), report(True))
    assert changed_data["comparability_checks"]["same_data_fingerprint"]


def test_missing_or_malformed_report_is_rejected(tmp_path):
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report(False)))
    assert load_report(path)["cases"][0]["passed"] is False
    path.write_text(json.dumps(report(False) | {"cases": [{"id": "other", "passed": True}]}))
    with pytest.raises(ValueError):
        load_report(path)
    path.write_bytes(b" " * (8 * 1024 * 1024 + 1))
    with pytest.raises(ValueError):
        load_report(path)
