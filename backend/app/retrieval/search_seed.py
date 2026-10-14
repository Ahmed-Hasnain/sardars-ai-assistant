import sys

import httpx

from app.core.config import Settings
from app.retrieval.seed_config import COLLECTION, DIMENSIONS, MODEL
from app.retrieval.authorization import ALLOWED_VISIBILITIES


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

        response = client.post(
            f"{settings.qdrant_base_url.rstrip('/')}/collections/{COLLECTION}/points/query",
            json={
                "query": vector,
                "filter": point_filter,
                "limit": 3,
                "with_payload": True,
                "with_vector": False,
            },
        )
        response.raise_for_status()

    return response.json()["result"]["points"]


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
