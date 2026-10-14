"""Source-registry policy and transaction work for the local website importer.

This trusted local-operator path is limited to the already owner-authorized
public Sardars site. It is not an authenticated upload API.
"""

from dataclasses import dataclass
from typing import Literal, Protocol

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import SourceRegistration
from app.ingestion.prepare_site import MAX_SELECTED_DOCUMENTS, prepare_chunks
from app.ingestion.site_documents import WebsiteDocument


AUTHORIZATION_BASIS = "owner_authorized_site_for_internal_use"


class WebsiteIndex(Protocol):
    def check_collection(self) -> None: ...
    def upsert_chunks(self, chunks: list[dict], authorization: dict[str, str]) -> None: ...


@dataclass(frozen=True)
class PlannedSource:
    source_id: str
    url: str
    content_sha256: str
    fetched_at: str
    registration: Literal["new", "existing"]
    chunks: int


@dataclass(frozen=True)
class ImportResult:
    status: Literal["preview", "completed"]
    new_sources: int
    indexed_chunks: int
    sources: list[PlannedSource]


def plan_import(db: Session, documents: list[WebsiteDocument], *, lock: bool = False) -> ImportResult:
    """Validate the complete selection before any registration or network write."""
    if not 1 <= len(documents) <= MAX_SELECTED_DOCUMENTS:
        raise ValueError("Import must contain between 1 and 10 documents")
    if len({document.source_id for document in documents}) != len(documents):
        raise ValueError("Import contains duplicate sources")
    # Revalidate even if a caller constructed a model without normal validation.
    documents = [WebsiteDocument.model_validate(document.model_dump(mode="json")) for document in documents]
    query = select(SourceRegistration).where(or_(
        SourceRegistration.source_id.in_([document.source_id for document in documents]),
        SourceRegistration.url.in_([document.url for document in documents]),
    ))
    if lock:
        query = query.with_for_update()
    registrations = list(db.scalars(query))
    existing_by_id = {source.source_id: source for source in registrations}
    existing_by_url = {source.url: source for source in registrations}
    sources: list[PlannedSource] = []
    for document in documents:
        source = existing_by_id.get(document.source_id) or existing_by_url.get(document.url)
        if source is not None:
            if not source.is_active:
                raise ValueError("A selected source is disabled; import will not reactivate it")
            if (
                source.source_id != document.source_id or source.url != document.url
                or source.source_type != document.source_type
                or source.visibility != "public"
            ):
                raise ValueError("A selected source has conflicting identity or restricted visibility")
            if source.content_sha256 != document.content_sha256:
                raise ValueError("A selected source has changed content; synchronization is Step 3")
        sources.append(PlannedSource(
            document.source_id, document.url, document.content_sha256,
            document.fetched_at.isoformat(), "existing" if source is not None else "new",
            len(prepare_chunks([document])),
        ))
    return ImportResult("preview", sum(source.registration == "new" for source in sources), 0, sources)


def apply_import(db: Session, documents: list[WebsiteDocument], indexer: WebsiteIndex) -> ImportResult:
    """Caller must commit only on success and roll back on failure.

New sources are invisible to other sessions until that commit. A failed vector
write may leave unregistered points; retrieval excludes unknown registrations.
Existing rows are locked while writing to preserve permissions and checksums.
"""
    plan = plan_import(db, documents, lock=True)
    indexer.check_collection()
    for source in plan.sources:
        if source.registration == "new":
            document = next(document for document in documents if document.source_id == source.source_id)
            db.add(SourceRegistration(
                source_id=document.source_id, url=document.url,
                source_type=document.source_type, visibility="public",
                content_sha256=document.content_sha256, is_active=True,
                authorization_basis=AUTHORIZATION_BASIS,
            ))
    # Detect database constraints before creating vectors. These rows remain
    # uncommitted until the CLI's transaction context exits successfully.
    db.flush()
    registrations = {
        source.source_id: source.authorization_basis
        for source in db.scalars(select(SourceRegistration).where(
            SourceRegistration.source_id.in_([document.source_id for document in documents])
        ))
    }
    chunks = prepare_chunks(documents)
    indexer.upsert_chunks(chunks, registrations)
    return ImportResult("completed", plan.new_sources, len(chunks), plan.sources)
