import sys
import re

import httpx

from app.core.config import Settings
from app.retrieval.seed_config import COLLECTION, DIMENSIONS, MODEL
from app.retrieval.authorization import ALLOWED_VISIBILITIES
from app.retrieval.limits import CANDIDATE_LIMIT


def _query(question: str, conditions: list[dict], visibility: set[str] | None = None) -> list[dict]:
    if not question.strip():
        raise ValueError("Question cannot be blank")

    settings = Settings()
    with httpx.Client(timeout=settings.ollama_timeout_seconds) as client:
        point_filter: dict = {"must": conditions}
        if visibility is not None:
            point_filter["should"] = [
                {"key": "visibility", "match": {"value": value}}
                for value in sorted(visibility)
            ]
        response = client.post(
            f"{settings.ollama_base_url.rstrip('/')}/api/embed",
            json={"model": MODEL, "input": question, "truncate": False},
        )
        response.raise_for_status()
        vector = response.json()["embeddings"][0]

        if len(vector) != DIMENSIONS:
            raise ValueError("Unexpected query embedding dimensions")

        preferred = []
        # Preserve the existing narrow Bongio definition when unrelated short
        # titles outrank its descriptive company profile in a larger corpus.
        # This is a retrieval hint; SQL authorization and source-text checks still
        # decide whether any point is usable. No brand fact is stored here.
        if settings.brand_definition_profile_url and re.fullmatch(r"\s*what is bongio\s*\??\s*", question, re.I):
            response = client.post(
                f"{settings.qdrant_base_url.rstrip('/')}/collections/{COLLECTION}/points/scroll",
                json={"filter": {**point_filter, "must": [*conditions,
                       {"key": "url", "match": {"value": settings.brand_definition_profile_url}}]},
                      "limit": 2, "with_payload": True, "with_vector": False},
            )
            response.raise_for_status()
            preferred = response.json()["result"]["points"]
            if not isinstance(preferred, list) or len(preferred) > 2:
                raise ValueError("Unexpected profile retrieval response")

        response = client.post(
            f"{settings.qdrant_base_url.rstrip('/')}/collections/{COLLECTION}/points/query",
            json={
                "query": vector,
                "filter": point_filter,
                "limit": CANDIDATE_LIMIT - len(preferred),
                "with_payload": True,
                "with_vector": False,
            },
        )
        response.raise_for_status()

        points = response.json()["result"]["points"]
        if not isinstance(points, list) or len(points) > CANDIDATE_LIMIT - len(preferred):
            raise ValueError("Unexpected retrieval candidate count")
    result = []
    seen = set()
    for point in preferred + points:
        if not isinstance(point, dict) or not isinstance(point.get("id"), (str, int)):
            raise ValueError("Unexpected retrieval point")
        if point["id"] not in seen:
            seen.add(point["id"])
            result.append(point)
    return result


def search_approved(question: str) -> list[dict]:
    return _query(
        question,
        [
            {"key": "visibility", "match": {"value": "public"}},
            {"key": "review_status", "match": {"value": "approved"}},
            {"key": "prototype_only", "match": {"value": False}},
        ],
    )


def search_for_role(question: str, role: str) -> list[dict]:
    """Prefilter permitted visibility; PostgreSQL still authorizes each point."""
    visibility = ALLOWED_VISIBILITIES.get(role)
    if visibility is None:
        return []
    return _query(
        question,
        [
            {"key": "review_status", "match": {"value": "approved"}},
            {"key": "prototype_only", "match": {"value": False}},
        ],
        visibility,
    )


def fetch_product_points(urls: list[str], role: str) -> list[dict]:
    """Fetch only exact product URLs; caller still runs PostgreSQL authorization."""
    visibility = ALLOWED_VISIBILITIES.get(role)
    if not visibility or len(urls) > 3:
        return []
    settings = Settings()
    points: list[dict] = []
    with httpx.Client(timeout=min(settings.ollama_timeout_seconds, 10.0)) as client:
        for url in urls:
            response = client.post(
                f"{settings.qdrant_base_url.rstrip('/')}/collections/{COLLECTION}/points/scroll",
                json={
                    "filter": {
                        "must": [
                            {"key": "url", "match": {"value": url}},
                            {"key": "source_type", "match": {"value": "products"}},
                            {"key": "review_status", "match": {"value": "approved"}},
                            {"key": "prototype_only", "match": {"value": False}},
                        ],
                        "should": [{"key": "visibility", "match": {"value": value}}
                                   for value in sorted(visibility)],
                    },
                    "limit": 16,
                    "with_payload": True,
                    "with_vector": False,
                },
            )
            response.raise_for_status()
            batch = response.json()["result"]["points"]
            if not isinstance(batch, list) or len(batch) > 16 or any(not isinstance(p, dict) for p in batch):
                raise ValueError("Unexpected product retrieval response")
            points.extend(batch)
    return points


def search_prototype(question: str) -> list[dict]:
    return _query(
        question,
        [
            {"key": "visibility", "match": {"value": "public"}},
            {"key": "review_status", "match": {"value": "pending"}},
            {"key": "prototype_only", "match": {"value": True}},
        ],
    )


def main() -> None:
    arguments = sys.argv[1:]
    approved_only = bool(arguments and arguments[0] == "--approved")
    if approved_only:
        arguments = arguments[1:]
    if not arguments:
        raise SystemExit(
            'Usage: python -m app.retrieval.search_seed [--approved] "question"'
        )

    question = " ".join(arguments)
    points = (
        search_approved(question) if approved_only else search_prototype(question)
    )

    mode = "APPROVED" if approved_only else "PROTOTYPE"
    print(f"{mode} SEARCH — {len(points)} matching chunks")
    for rank, point in enumerate(points, start=1):
        payload = point["payload"]
        print(f"\n{rank}. {payload['title']} | score: {point['score']:.3f}")
        print(f"Source: {payload['url']}")
        print(f"Review: {payload['review_status']}")
        print(f"Text: {payload['text']}")


if __name__ == "__main__":
    main()
