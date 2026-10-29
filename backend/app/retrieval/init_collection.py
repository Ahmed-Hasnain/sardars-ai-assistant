"""Create the empty Qdrant collection needed by a clean local stack."""

import time

import httpx

from app.core.config import Settings
from app.retrieval.seed_config import COLLECTION, DIMENSIONS


def ensure_collection(client: httpx.Client, base_url: str) -> bool:
    """Create only when absent; refuse to use an incompatible existing index."""
    url = f"{base_url.rstrip('/')}/collections/{COLLECTION}"
    response = client.get(url)
    if response.status_code == 404:
        created = client.put(url, json={"vectors": {"size": DIMENSIONS, "distance": "Cosine"}})
        created.raise_for_status()
        response = client.get(url)
        was_created = True
    else:
        was_created = False
    response.raise_for_status()
    try:
        vectors = response.json()["result"]["config"]["params"]["vectors"]
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("Qdrant returned an invalid collection schema") from exc
    if (
        not isinstance(vectors, dict)
        or type(vectors.get("size")) is not int
        or vectors["size"] != DIMENSIONS
        or vectors.get("distance") != "Cosine"
    ):
        raise RuntimeError("Qdrant collection has a different vector schema")
    return was_created


def main() -> None:
    base_url = Settings().qdrant_base_url
    with httpx.Client(timeout=5) as client:
        for attempt in range(30):
            try:
                ready = client.get(f"{base_url.rstrip('/')}/collections")
                ready.raise_for_status()
                break
            except httpx.HTTPError:
                if attempt == 29:
                    raise SystemExit("Qdrant did not become ready") from None
                time.sleep(2)
        try:
            created = ensure_collection(client, base_url)
        except (httpx.HTTPError, RuntimeError) as exc:
            raise SystemExit(f"Qdrant collection initialization failed: {exc}") from None
    print(f"Qdrant collection {COLLECTION}: {'created' if created else 'already compatible'}")


if __name__ == "__main__":
    main()
