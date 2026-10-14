"""Bounded Ollama embedding and Qdrant writes for controlled website imports."""

import json
import math
import time
from datetime import datetime

import httpx

from app.core.config import Settings
from app.retrieval.seed_config import COLLECTION, DIMENSIONS, MODEL


EMBEDDING_BATCH_SIZE = 8
INDEX_CHECK_BATCH_SIZE = 8
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class IndexingError(RuntimeError):
    """Safe import failure without raw service responses or document text."""


def _finite_number(value: object) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _indexed_payload(chunk: dict, authorization_basis: str) -> dict:
    return {
        **{key: value for key, value in chunk.items() if key != "id"},
        "review_status": "approved", "prototype_only": False,
        "approval_basis": authorization_basis, "embedding_model": MODEL,
    }


def _point_matches(point: dict, chunk: dict, authorization_basis: str) -> bool:
    payload = point.get("payload")
    vector = point.get("vector")
    if (
        not isinstance(payload, dict) or not isinstance(vector, list)
        or len(vector) != DIMENSIONS or any(not _finite_number(value) for value in vector)
    ):
        return False
    fetched_at = payload.get("fetched_at")
    try:
        if not isinstance(fetched_at, str) or datetime.fromisoformat(fetched_at).utcoffset() is None:
            return False
    except ValueError:
        return False
    # An unchanged import retains its last indexed fetch date. Checking saved
    # content is not a new website fetch or an assertion of business freshness.
    expected = _indexed_payload(chunk, authorization_basis)
    return all(
        type(payload.get(key)) is type(value) and payload[key] == value
        for key, value in expected.items() if key != "fetched_at"
    )


class WebsiteIndexer:
    def __init__(self, settings: Settings, client: httpx.Client):
        self.settings = settings
        self.client = client
        self.deadline = time.monotonic() + settings.import_timeout_seconds

    def _timeout(self) -> float:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise IndexingError("Import exceeded its processing time budget")
        return min(self.settings.ollama_timeout_seconds, remaining)

    def _request(self, method: str, url: str, **kwargs: object) -> dict:
        try:
            with self.client.stream(method, url, timeout=self._timeout(), **kwargs) as response:
                response.raise_for_status()
                content = bytearray()
                for block in response.iter_bytes(chunk_size=64 * 1024):
                    self._timeout()
                    content.extend(block)
                    if len(content) > MAX_RESPONSE_BYTES:
                        raise IndexingError("Local service response exceeds the size limit")
        except httpx.HTTPError as exc:
            raise IndexingError("Local embedding or vector service unavailable") from exc
        self._timeout()
        try:
            body = json.loads(content)
        except (ValueError, RecursionError) as exc:
            raise IndexingError("Local service returned invalid JSON") from exc
        if not isinstance(body, dict):
            raise IndexingError("Local service returned an invalid response")
        return body

    def check_collection(self) -> None:
        body = self._request(
            "GET", f"{self.settings.qdrant_base_url.rstrip('/')}/collections/{COLLECTION}",
        )
        try:
            vectors = body["result"]["config"]["params"]["vectors"]
            matches = (
                type(vectors["size"]) is int and vectors["size"] == DIMENSIONS
                and vectors["distance"] == "Cosine"
            )
        except (KeyError, TypeError):
            matches = False
        if not matches:
            raise IndexingError("Qdrant collection must use the recorded 1024-dimensional cosine schema")

    def source_is_current(self, chunks: list[dict], authorization_basis: str) -> bool:
        """Check every expected point and vector, with bounded source pagination.

Read by source ID without approval filtering so inconsistent or extra points
cannot disappear from the completeness check. Never search semantically here.
"""
        if not chunks or len({chunk["source_id"] for chunk in chunks}) != 1:
            raise IndexingError("Index check requires one prepared source")
        expected = {chunk["id"]: chunk for chunk in chunks}
        if len(expected) != len(chunks):
            raise IndexingError("Index check contains duplicate chunk IDs")
        points: dict[str, dict] = {}
        offset: str | int | None = None
        offsets: set[str | int] = set()
        while True:
            limit = min(INDEX_CHECK_BATCH_SIZE, len(expected) + 1 - len(points))
            query = {
                "filter": {"must": [{"key": "source_id", "match": {"value": chunks[0]["source_id"]}}]},
                "limit": limit, "with_payload": True, "with_vector": True,
            }
            if offset is not None:
                query["offset"] = offset
            body = self._request(
                "POST", f"{self.settings.qdrant_base_url.rstrip('/')}/collections/{COLLECTION}/points/scroll",
                json=query,
            )
            result = body.get("result")
            if (
                body.get("status") != "ok" or not isinstance(result, dict)
                or not isinstance(result.get("points"), list)
                or "next_page_offset" not in result or len(result["points"]) > limit
            ):
                raise IndexingError("Qdrant returned an invalid index-check response")
            for point in result["points"]:
                if not isinstance(point, dict) or not isinstance(point.get("id"), str):
                    raise IndexingError("Qdrant returned an invalid index-check point")
                point_id = point["id"]
                if point_id not in expected:
                    raise IndexingError("Source has unexpected chunks; cleanup is Step 3B")
                if point_id in points:
                    raise IndexingError("Qdrant repeated a point during the index check")
                points[point_id] = point
            offset = result["next_page_offset"]
            if offset is None:
                break
            if type(offset) not in (str, int) or offset in offsets or not result["points"]:
                raise IndexingError("Qdrant returned invalid index-check pagination")
            offsets.add(offset)
        return len(points) == len(expected) and all(
            _point_matches(points[point_id], chunk, authorization_basis)
            for point_id, chunk in expected.items()
        )

    def upsert_chunks(self, chunks: list[dict], authorization: dict[str, str]) -> None:
        """Caller supplies registry-checked chunks and their authorization basis."""
        for start in range(0, len(chunks), EMBEDDING_BATCH_SIZE):
            batch = chunks[start:start + EMBEDDING_BATCH_SIZE]
            body = self._request(
                "POST", f"{self.settings.ollama_base_url.rstrip('/')}/api/embed",
                json={
                    "model": MODEL, "input": [chunk["text"] for chunk in batch],
                    "truncate": False, "keep_alive": self.settings.ollama_keep_alive,
                },
            )
            vectors = body.get("embeddings")
            if (
                not isinstance(vectors, list) or len(vectors) != len(batch)
                or any(
                    not isinstance(vector, list) or len(vector) != DIMENSIONS
                    or any(not _finite_number(value) for value in vector)
                    for vector in vectors
                )
            ):
                raise IndexingError("Unexpected embedding count, dimensions, or numeric values")
            points = [
                {
                    "id": chunk["id"], "vector": vector,
                    "payload": _indexed_payload(chunk, authorization[chunk["source_id"]]),
                }
                for chunk, vector in zip(batch, vectors, strict=True)
            ]
            result = self._request(
                "PUT", f"{self.settings.qdrant_base_url.rstrip('/')}/collections/{COLLECTION}/points",
                params={"wait": "true"}, json={"points": points},
            )
            if (
                result.get("status") != "ok" or not isinstance(result.get("result"), dict)
                or result["result"].get("status") != "completed"
            ):
                raise IndexingError("Qdrant did not confirm completion of the index write")
