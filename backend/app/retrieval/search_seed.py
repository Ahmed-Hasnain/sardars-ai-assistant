import sys
import re

import httpx

from app.api.answer_deadlines import remaining_timeout
from app.core.config import Settings
from app.retrieval.seed_config import COLLECTION, DIMENSIONS, MODEL
from app.retrieval.authorization import ALLOWED_VISIBILITIES
from app.retrieval.limits import CANDIDATE_LIMIT


COMPANY_OVERVIEW = re.compile(
    r"\b(?:business|industry|sector|category|speciali[sz]\w*|sell|provid\w*|offer\w*)\b",
    re.I,
)
COMPANY_REFERENCE = re.compile(r"\b(?:sardars?|you|your|yours|we|our|ours)\b", re.I)
COMPANY_IDENTITY_QUESTION = re.compile(
    r"^\s*(?:what is|who are|tell me about|describe)\s+sardars\s*\??\s*$", re.I,
)
PRODUCT_DISCOVERY_QUESTION = re.compile(r"\b(?:what|which)\b.{0,100}\bproducts?\b", re.I)


def is_company_overview_question(question: str) -> bool:
    return bool(COMPANY_REFERENCE.search(question) and COMPANY_OVERVIEW.search(question))


def is_company_identity_question(question: str) -> bool:
    return bool(COMPANY_IDENTITY_QUESTION.fullmatch(question))


def _needs_company_profile(question: str) -> bool:
    return bool(
        re.fullmatch(r"\s*what is bongio\s*\??\s*", question, re.I)
        or (re.search(r"\bbrands\b", question, re.I)
            and re.search(r"\b(?:sardars?|they|you|your|our|we|offer\w*|carr(?:y|ies)|sell\w*)\b",
                          question, re.I))
        or is_company_identity_question(question)
        or is_company_overview_question(question)
    )


def _query(question: str, conditions: list[dict], visibility: set[str] | None = None) -> list[dict]:
    if not question.strip():
        raise ValueError("Question cannot be blank")

    settings = Settings()
    with httpx.Client(timeout=remaining_timeout(settings.ollama_timeout_seconds)) as client:
        point_filter: dict = {"must": [*conditions]}
        # A request for a product needs product-page evidence. In the full
        # corpus, generic articles otherwise crowd the relevant product out
        # of the eight-candidate budget.
        if PRODUCT_DISCOVERY_QUESTION.search(question):
            point_filter["must"].append({"key": "source_type", "match": {"value": "products"}})
        if visibility is not None:
            point_filter["should"] = [
                {"key": "visibility", "match": {"value": value}}
                for value in sorted(visibility)
            ]
        response = client.post(
            f"{settings.ollama_base_url.rstrip('/')}/api/embed",
            json={"model": MODEL, "input": question, "truncate": False},
            timeout=remaining_timeout(settings.ollama_timeout_seconds),
        )
        response.raise_for_status()
        vector = response.json()["embeddings"][0]

        if len(vector) != DIMENSIONS:
            raise ValueError("Unexpected query embedding dimensions")

        preferred = []
        # Keep the registered company profile within the bounded candidate set
        # for broad company-overview questions and the existing Bongio baseline.
        # PostgreSQL authorization still decides whether these points are usable.
        if settings.brand_definition_profile_url and _needs_company_profile(question):
            response = client.post(
                f"{settings.qdrant_base_url.rstrip('/')}/collections/{COLLECTION}/points/scroll",
                json={"filter": {**point_filter, "must": [*point_filter["must"],
                       {"key": "url", "match": {"value": settings.brand_definition_profile_url}}]},
                      "limit": 2, "with_payload": True, "with_vector": False},
                timeout=remaining_timeout(settings.ollama_timeout_seconds),
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
            timeout=remaining_timeout(settings.ollama_timeout_seconds),
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
    with httpx.Client(timeout=remaining_timeout(min(settings.ollama_timeout_seconds, 10.0))) as client:
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
                timeout=remaining_timeout(min(settings.ollama_timeout_seconds, 10.0)),
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
