"""Profile hints stay bounded and use the same role/approval prefilters."""

import json

import httpx
import pytest

from app.core.config import Settings
from app.retrieval import search_seed
from app.retrieval.seed_config import DIMENSIONS

HTTPX_CLIENT = httpx.Client


def setup(monkeypatch, preferred, semantic, *, profile_url="https://sardarandco.com/pages/about-us"):
    calls = []
    settings = Settings(_env_file=None, db_user="test", db_name="test", db_password="test",
                        brand_definition_profile_url=profile_url)

    def handle(request):
        body = json.loads(request.content)
        calls.append((request.url.path, body))
        if request.url.path == "/api/embed":
            return httpx.Response(200, json={"embeddings": [[0.1] * DIMENSIONS]})
        return httpx.Response(200, json={"result": {"points": preferred if request.url.path.endswith("/scroll") else semantic}})

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
    scroll, query = calls[1:]
    assert scroll[1]["limit"] == 2 and query[1]["limit"] == 6
    for _, body in (scroll, query):
        assert {condition["match"]["value"] for condition in body["filter"]["should"]} == {"public", "staff"}
        assert {"key": "review_status", "match": {"value": "approved"}} in body["filter"]["must"]


def test_missing_profile_keeps_full_semantic_budget(monkeypatch):
    calls = setup(monkeypatch, [], [{"id": "other"}])
    assert search_seed.search_for_role("What is Bongio?", "admin") == [{"id": "other"}]
    assert calls[-1][1]["limit"] == 8
    assert len(calls[1][1]["filter"]["should"]) == 3


def test_other_questions_and_disabled_hint_use_semantic_search_only(monkeypatch):
    calls = setup(monkeypatch, [], [])
    assert search_seed.search_for_role("What is Anotherbrand?", "staff") == []
    assert len(calls) == 2
    calls = setup(monkeypatch, [], [], profile_url=None)
    assert search_seed.search_for_role("What is Bongio?", "staff") == []
    assert len(calls) == 2


@pytest.mark.parametrize("preferred,semantic", [([{"id": str(i)} for i in range(3)], []),
    ([], [{"id": str(i)} for i in range(9)])])
def test_oversized_service_results_fail_before_evidence(monkeypatch, preferred, semantic):
    setup(monkeypatch, preferred, semantic)
    with pytest.raises(ValueError, match="Unexpected"):
        search_seed.search_for_role("What is Bongio?", "staff")
