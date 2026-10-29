"""Profile hints stay bounded and use the same role/approval prefilters."""

import json

import httpx
import pytest

from app.core.config import Settings
from app.retrieval import search_seed, selection
from app.retrieval.rerank import rerank
from app.retrieval.seed_config import DIMENSIONS

HTTPX_CLIENT = httpx.Client


def setup(monkeypatch, preferred, semantic, *, lexical=None, profile_url="https://sardarandco.com/pages/about-us"):
    calls = []
    settings = Settings(_env_file=None, db_user="test", db_name="test", db_password="test",
                        brand_definition_profile_url=profile_url)

    def handle(request):
        body = json.loads(request.content)
        calls.append((request.url.path, body))
        if request.url.path == "/api/embed":
            return httpx.Response(200, json={"embeddings": [[0.1] * DIMENSIONS]})
        points = (lexical or []) if any(c.get("key") == "text" for c in body.get("filter", {}).get("must", [])) else (
            preferred if request.url.path.endswith("/scroll") else semantic)
        return httpx.Response(200, json={"result": {"points": points}})

    client = HTTPX_CLIENT(transport=httpx.MockTransport(handle))
    monkeypatch.setattr(search_seed, "Settings", lambda: settings)
    monkeypatch.setattr(search_seed.httpx, "Client", lambda **kwargs: client)
    return calls


def test_bongio_profile_lookup_and_semantic_search_share_staff_permission_filters(monkeypatch):
    preferred = [{"id": "profile-0"}, {"id": "profile-1"}]
    semantic = [{"id": str(index)} for index in range(6)]
    calls = setup(monkeypatch, preferred, semantic)
    points = search_seed.search_for_role("What is Bongio?", "staff")
    assert points == preferred + semantic and len(points) == 8
    scroll, query = calls[1:3]
    assert scroll[1]["limit"] == 2 and query[1]["limit"] == 30
    for _, body in (scroll, query):
        assert {condition["match"]["value"] for condition in body["filter"]["should"]} == {"public", "staff"}
        assert {"key": "review_status", "match": {"value": "approved"}} in body["filter"]["must"]


@pytest.mark.parametrize("question", [
    "What is the category of business in which Sardars deal?",
    "Tell me about Sardars and what it sells",
])
def test_company_business_question_includes_authorized_profile(monkeypatch, question):
    preferred = [{"id": "profile-0"}, {"id": "profile-1"}]
    semantic = [{"id": str(index)} for index in range(6)]
    calls = setup(monkeypatch, preferred, semantic)

    points = search_seed.search_for_role(question, "staff")

    assert points == preferred + semantic
    scroll, query = calls[1:3]
    assert scroll[1]["limit"] == 2 and query[1]["limit"] == 30
    assert {condition["match"]["value"] for condition in scroll[1]["filter"]["should"]} == {"public", "staff"}
    assert {"key": "url", "match": {"value": "https://sardarandco.com/pages/about-us"}} in scroll[1]["filter"]["must"]


def test_missing_profile_keeps_full_semantic_budget(monkeypatch):
    calls = setup(monkeypatch, [], [{"id": "other"}])
    assert search_seed.search_for_role("What is Bongio?", "admin") == [{"id": "other"}]
    assert calls[-1][1]["limit"] == 32
    assert len(calls[1][1]["filter"]["should"]) == 3


def test_other_questions_and_disabled_hint_use_semantic_search_only(monkeypatch):
    calls = setup(monkeypatch, [], [])
    assert search_seed.search_for_role("What is Anotherbrand?", "staff") == []
    assert len(calls) == 2
    calls = setup(monkeypatch, [], [], profile_url=None)
    assert search_seed.search_for_role("What is Bongio?", "staff") == []
    assert len(calls) == 2


def test_product_discovery_uses_visible_product_pages_within_candidate_limit(monkeypatch):
    calls = setup(monkeypatch, [], [{"id": "product"}])
    assert search_seed.search_for_role("What bathroom storage product does Sardars describe?", "staff") == [{"id": "product"}]
    assert len(calls) == 3
    query = calls[1][1]
    assert query["limit"] == 32
    assert {"key": "source_type", "match": {"value": "products"}} in query["filter"]["must"]
    assert {condition["match"]["value"] for condition in query["filter"]["should"]} == {"public", "staff"}


def test_later_exact_title_is_promoted_without_expanding_answer_budget(monkeypatch):
    distractors = [{"id": str(i), "payload": {"title": "Basin fitting", "text": "Ceramic sink."}}
                   for i in range(12)]
    target = {"id": "target", "payload": {"title": "Square E corner basin",
                                             "text": "The basin includes an overflow."}}
    calls = setup(monkeypatch, [], [*distractors, target])
    question = "Does the Square E corner basin include overflow?"
    points = search_seed.search_for_role(question, "staff")
    assert len(points) == 13 and points[-1] == target
    monkeypatch.setattr(selection, "authorized_points", lambda db, role, rows: rows)
    selected = selection.select_authorized_points(None, "staff", question, points)
    assert len(selected) == 8 and selected[0] == target
    assert calls[1][1]["limit"] == 32
    assert {condition["match"]["value"] for condition in calls[1][1]["filter"]["should"]} == {"public", "staff"}


def test_lexical_candidates_share_permissions_and_are_post_authorized(monkeypatch):
    lexical = [{"id": "article", "payload": {"title": "Bathroom fittings", "text": "Steel and brass."}}]
    calls = setup(monkeypatch, [], [], lexical=lexical)
    points = search_seed.search_for_role(
        "What does Sardars say about stainless steel or brass for durability?", "staff")
    assert points == lexical
    body = calls[-1][1]
    assert body["limit"] == search_seed.LEXICAL_POOL_LIMIT
    assert {condition["match"]["value"] for condition in body["filter"]["should"]} == {"public", "staff"}
    assert {"key": "review_status", "match": {"value": "approved"}} in body["filter"]["must"]
    assert {"key": "text", "match": {"text": "stainless steel brass durability"}} in body["filter"]["must"]


def test_selection_filters_sources_before_reranking(monkeypatch):
    question = "Does the Square E corner basin include overflow?"
    hidden = [{"id": str(i), "payload": {"title": "Square E corner basin overflow", "text": "overflow"}}
              for i in range(20)]
    visible = {"id": "visible", "payload": {"title": "Square E corner basin", "text": "overflow"}}
    monkeypatch.setattr(selection, "authorized_points", lambda db, role, rows: [visible])
    assert selection.select_authorized_points(None, "staff", question, [*hidden, visible]) == [visible]


def test_broad_discovery_keeps_semantic_order_after_authorization(monkeypatch):
    rows = [{"id": str(i), "payload": {"title": "Storage product", "text": "bathroom storage"}}
            for i in range(9)]
    monkeypatch.setattr(selection, "authorized_points", lambda db, role, points: points)
    assert selection.select_authorized_points(
        None, "staff", "What bathroom storage product does Sardars describe?", rows,
    ) == rows[:8]


def test_company_profile_remains_first_after_authorization(monkeypatch):
    profile = {"id": "profile", "payload": {
        "url": "https://sardarandco.com/pages/about-us", "title": "About Us", "text": "Sardars lists brands.",
    }}
    other = {"id": "other", "payload": {"url": "https://sardarandco.com/blogs/news/brands",
                                          "title": "Brands Sardars offers", "text": "Brands are featured."}}
    monkeypatch.setattr(selection, "authorized_points", lambda db, role, points: points)
    assert selection.select_authorized_points(None, "staff", "Which brands does Sardars mention?",
                                              [other, profile])[0] == profile


def test_compact_answer_sentence_beats_scattered_seo_terms():
    distractors = [{"payload": {"title": f"Soap Holder {number}",
                                "text": "Mild finish. This soap holder is used in bathrooms. Water is nearby."}}
                   for number in range(8)]
    article = {"payload": {"title": "Maintaining Sanitary Fittings",
                           "text": "Clean faucets and showerheads with mild soap and water to preserve their finish."}}
    ranked = rerank("What does Sardars say about mild soap and water?", distractors + [article], 8)
    assert article in ranked


def test_malformed_retrieval_text_cannot_crash_reranking():
    malformed = {"payload": {"title": "A product", "text": None}}
    valid = {"payload": {"title": "Steel seat", "text": "The steel seat uses aluminium."}}
    assert rerank("What material does the steel seat use?", [malformed, valid], 2)[0] == valid


def test_search_cli_displays_lexical_point_without_semantic_score(monkeypatch, capsys):
    point = {"id": "lexical", "payload": {"title": "Materials", "url": "https://sardarandco.com/pages/about-us",
              "review_status": "approved", "text": "Stainless steel."}}
    monkeypatch.setattr(search_seed, "search_prototype", lambda question: [point])
    monkeypatch.setattr(search_seed.sys, "argv", ["search_seed", "materials"])
    search_seed.main()
    assert "score: lexical" in capsys.readouterr().out


@pytest.mark.parametrize("preferred,semantic", [([{"id": str(i)} for i in range(3)], []),
    ([], [{"id": str(i)} for i in range(33)])])
def test_oversized_service_results_fail_before_evidence(monkeypatch, preferred, semantic):
    setup(monkeypatch, preferred, semantic)
    with pytest.raises(ValueError, match="Unexpected"):
        search_seed.search_for_role("What is Bongio?", "staff")
