"""Bounded local-model/index requests and malformed service responses."""

import json

import httpx
import pytest

from app.core.config import Settings
from app.ingestion.site_index import EMBEDDING_BATCH_SIZE, IndexingError, WebsiteIndexer
from app.retrieval import search_seed
from app.retrieval.seed_config import COLLECTION, DIMENSIONS


def _settings() -> Settings:
    return Settings(
        _env_file=None, db_user="test", db_name="test", db_password="test",
        ollama_base_url="http://embedding.local:11434", qdrant_base_url="http://vectors.local:6333",
    )


def _chunk(index: int = 0) -> dict:
    return {
        "id": str(index), "source_id": "a" * 64, "url": "https://sardarandco.com/pages/about-us",
        "visibility": "public", "review_status": "pending", "text": "Test text",
        "content_sha256": "b" * 64,
    }


@pytest.mark.parametrize("schema", [
    {}, {"size": 768, "distance": "Cosine"}, {"size": DIMENSIONS, "distance": "Dot"},
    {"size": "1024", "distance": "Cosine"}, {"named": {"size": DIMENSIONS, "distance": "Cosine"}},
])
def test_collection_schema_must_match_before_embedding(schema: dict) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET" and request.url.host == "vectors.local"
        return httpx.Response(200, json={"result": {"config": {"params": {"vectors": schema}}}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client, pytest.raises(IndexingError, match="schema"):
        WebsiteIndexer(_settings(), client).check_collection()


@pytest.mark.parametrize("vectors", [
    None, [], [[0.1] * 768], ["not a vector"], [[True] * DIMENSIONS],
    [[None] * DIMENSIONS], [[float("nan")] * DIMENSIONS], [[float("inf")] * DIMENSIONS],
    [[10 ** 400] * DIMENSIONS], [[0.1] * DIMENSIONS] * 2,
])
def test_bad_embeddings_are_refused_before_any_vector_write(vectors: object) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST" and request.url.host == "embedding.local"
        return httpx.Response(200, content=json.dumps({"embeddings": vectors}).encode())

    with httpx.Client(transport=httpx.MockTransport(handler)) as client, pytest.raises(IndexingError, match="embedding"):
        WebsiteIndexer(_settings(), client).upsert_chunks([_chunk()], {"a" * 64: "test_authorization"})


def test_requests_use_configured_services_bounded_batches_and_completed_writes() -> None:
    embedded_counts, indexed_counts = [], []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if request.url.path == "/api/embed":
            assert request.url.host == "embedding.local"
            embedded_counts.append(len(body["input"]))
            return httpx.Response(200, json={"embeddings": [[0.1] * DIMENSIONS for _ in body["input"]]})
        assert request.url.host == "vectors.local"
        assert request.url.path == f"/collections/{COLLECTION}/points"
        assert request.url.params["wait"] == "true"
        indexed_counts.append(len(body["points"]))
        assert all(point["payload"]["approval_basis"] == "test_authorization" for point in body["points"])
        return httpx.Response(200, json={"status": "ok", "result": {"status": "completed"}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        WebsiteIndexer(_settings(), client).upsert_chunks(
            [_chunk(index) for index in range(EMBEDDING_BATCH_SIZE + 1)], {"a" * 64: "test_authorization"},
        )
    assert embedded_counts == indexed_counts == [EMBEDDING_BATCH_SIZE, 1]


@pytest.mark.parametrize("result", [
    {}, {"status": "ok", "result": {}}, {"status": "ok", "result": {"status": "acknowledged"}},
    {"status": "error", "result": {"status": "completed"}}, {"status": "ok", "result": []},
])
def test_upsert_requires_confirmation_of_completion(result: dict) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"embeddings": [[0.1] * DIMENSIONS]})
        return httpx.Response(200, json=result)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client, pytest.raises(IndexingError, match="completion"):
        WebsiteIndexer(_settings(), client).upsert_chunks([_chunk()], {"a" * 64: "test_authorization"})


@pytest.mark.parametrize("content", [b"not JSON", b"[]", b"[" * 1100 + b"0" + b"]" * 1100])
def test_malformed_service_json_is_a_safe_error(content: bytes) -> None:
    with httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=content))) as client:
        with pytest.raises(IndexingError, match="invalid"):
            WebsiteIndexer(_settings(), client).check_collection()


def test_service_response_size_and_processing_time_are_bounded(monkeypatch) -> None:
    monkeypatch.setattr("app.ingestion.site_index.MAX_RESPONSE_BYTES", 10)
    handler = lambda _request: httpx.Response(200, content=b"x" * 11)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(IndexingError, match="size limit"):
            WebsiteIndexer(_settings(), client).check_collection()

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        indexer = WebsiteIndexer(_settings(), client)
        indexer.deadline = 0
        with pytest.raises(IndexingError, match="time budget"):
            indexer.check_collection()


@pytest.mark.parametrize("mode", ["timeout", "http_error"])
def test_network_failures_hide_service_details(mode: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if mode == "timeout":
            raise httpx.ReadTimeout("SECRET_SERVICE_DETAIL", request=request)
        return httpx.Response(500, text="SECRET_SERVICE_DETAIL")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client, pytest.raises(IndexingError) as error:
        WebsiteIndexer(_settings(), client).check_collection()
    assert "SECRET" not in str(error.value)


def test_seed_retrieval_uses_the_same_configured_services_and_collection(monkeypatch) -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/embed":
            return httpx.Response(200, json={"embeddings": [[0.1] * DIMENSIONS]})
        assert request.url.path == f"/collections/{COLLECTION}/points/query"
        assert json.loads(request.content)["limit"] == 3
        return httpx.Response(200, json={"result": {"points": []}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(search_seed, "Settings", _settings)
    monkeypatch.setattr(search_seed.httpx, "Client", lambda **_kwargs: client)

    assert search_seed.search_approved("Which brands?") == []
    assert [request.url.host for request in requests] == ["embedding.local", "vectors.local"]
