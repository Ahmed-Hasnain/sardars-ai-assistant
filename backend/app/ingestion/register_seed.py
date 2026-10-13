"""Register only the two owner-authorized website seed sources in PostgreSQL."""

from hashlib import sha256
import json

from sqlalchemy import select

from app.db.models import SourceRegistration
from app.db.session import SessionLocal
from app.ingestion.index_seed import CHUNKS_FILE
from app.ingestion.public_site import source_type


AUTHORIZED_SEED_URLS = {
    "https://sardarandco.com/pages/about-us",
    "https://sardarandco.com/products/shower-niche-pakistan",
}
BASIS = "owner_authorized_site_for_internal_use"


def main() -> None:
    chunks = [
        json.loads(line)
        for line in CHUNKS_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    urls = {chunk["url"] for chunk in chunks}
    if urls != AUTHORIZED_SEED_URLS:
        raise SystemExit("Seed chunks must contain exactly the two authorized URLs")

    records: dict[str, tuple[str, str, str]] = {}
    for chunk in chunks:
        url = chunk["url"]
        kind = source_type(url)
        if (
            chunk.get("source_id") != sha256(url.encode()).hexdigest()
            or chunk.get("visibility") != "public"
            or chunk.get("source_type") != kind
            or kind is None
            or not isinstance(chunk.get("content_sha256"), str)
            or len(chunk["content_sha256"]) != 64
        ):
            raise SystemExit("Invalid seed source metadata")
        record = (url, kind, chunk["content_sha256"])
        if chunk["source_id"] in records and records[chunk["source_id"]] != record:
            raise SystemExit("Conflicting versions of one seed source")
        records[chunk["source_id"]] = record

    added = 0
    with SessionLocal() as db:
        for source_id, (url, kind, checksum) in records.items():
            existing = db.scalar(
                select(SourceRegistration).where(SourceRegistration.source_id == source_id)
            )
            if existing is None:
                db.add(SourceRegistration(
                    source_id=source_id, url=url, source_type=kind,
                    content_sha256=checksum,
                    visibility="public", authorization_basis=BASIS,
                ))
                added += 1
            elif (
                existing.url, existing.source_type, existing.content_sha256,
                existing.visibility,
            ) != (url, kind, checksum, "public"):
                raise SystemExit("Existing source registration conflicts with the seed")
        db.commit()
    print(f"Registered {added} seed source(s); {len(records)} total. Existing disabled sources stay disabled.")


if __name__ == "__main__":
    main()
