"""Clean-stack index setup must be safe to repeat and reject schema drift."""

import json

import httpx
import pytest

from app.retrieval.init_collection import ensure_collection
from app.retrieval.seed_config import COLLECTION, DIMENSIONS


def test_creates_missing_collection_and_preserves_it_on_restart() -> None:
    state = {"exists": False, "put_count": 0}

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/collections/{COLLECTION}"
        if request.method == "PUT":
            assert json.loads(request.read()) == {
                "vectors": {"size": DIMENSIONS, "distance": "Cosine"},
            }
            state["exists"] = True
            state["put_count"] += 1
            return httpx.Response(200, json={"result": True})
        if not state["exists"]:
            return httpx.Response(404)
        return httpx.Response(200, json={"result": {"config": {"params": {
            "vectors": {"size": DIMENSIONS, "distance": "Cosine"},
        }}}})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert ensure_collection(client, "http://qdrant:6333") is True
        assert ensure_collection(client, "http://qdrant:6333") is False
    assert state["put_count"] == 1


def test_refuses_existing_collection_with_different_dimensions() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(200, json={"result": {"config": {"params": {
            "vectors": {"size": 768, "distance": "Cosine"},
        }}}})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(RuntimeError, match="different vector schema"):
            ensure_collection(client, "http://qdrant:6333")


def test_qdrant_error_is_not_treated_as_empty_collection() -> None:
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503))) as client:
        with pytest.raises(httpx.HTTPStatusError):
            ensure_collection(client, "http://qdrant:6333")
