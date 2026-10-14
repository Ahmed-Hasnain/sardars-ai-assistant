import json
from pathlib import Path
from app.ingestion.public_site import source_type

import httpx
from sqlalchemy import select

from app.db.models import SourceRegistration
from app.db.session import SessionLocal
from app.core.config import Settings
from app.retrieval.seed_config import COLLECTION, DIMENSIONS, MODEL

CHUNKS_FILE = Path("data/extracted/rag_seed_chunks.jsonl")


def main() -> None:
    chunks = [
        json.loads(line)
        for line in CHUNKS_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    if not chunks or any(
    chunk["visibility"] != "public"
    or source_type(chunk["url"]) != chunk["source_type"]
    for chunk in chunks ):
        raise ValueError("Only authorized Sardars website chunks can be indexed")

    with SessionLocal() as db:
        registrations = {
            source.source_id: source
            for source in db.scalars(select(SourceRegistration).where(
                SourceRegistration.source_id.in_({chunk["source_id"] for chunk in chunks})
            ))
        }
        if any(
            (source := registrations.get(chunk["source_id"])) is None
            or not source.is_active
            or source.visibility != "public"
            or source.url != chunk["url"]
            or source.source_type != chunk["source_type"]
            or source.content_sha256 != chunk["content_sha256"]
            for chunk in chunks
        ):
            raise ValueError("Register the active seed sources before indexing")

    settings = Settings()
    with httpx.Client(timeout=settings.ollama_timeout_seconds) as client:
        response = client.post(
            f"{settings.ollama_base_url.rstrip('/')}/api/embed",
            json={
                "model": MODEL,
                "input": [chunk["text"] for chunk in chunks],
                "truncate": False,
            },
        )
        response.raise_for_status()
        vectors = response.json()["embeddings"]

        if len(vectors) != len(chunks) or any(len(vector) != DIMENSIONS for vector in vectors):
            raise ValueError("Unexpected embedding count or dimensions")

        points = [
            {
                "id": chunk["id"],
                "vector": vector,
                "payload": {
                    **{
                        key: value
                        for key, value in chunk.items()
                        if key not in {"id", "review_status"}
                    },
                    "review_status": "approved",
                    "approval_basis": "owner_authorized_source_for_internal_use",
                    "embedding_model": MODEL,
                    "prototype_only": False,
                },
            }
            for chunk, vector in zip(chunks, vectors)
        ]

        response = client.put(
            f"{settings.qdrant_base_url.rstrip('/')}/collections/{COLLECTION}/points",
            params={"wait": "true"},
            json={"points": points},
        )
        response.raise_for_status()
        print(response.json())
        print(f"Stored {len(points)} internally authorized points")


if __name__ == "__main__":
    main()
