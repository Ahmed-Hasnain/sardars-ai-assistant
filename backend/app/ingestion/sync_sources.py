"""Staged source publication and bounded cleanup for durable website jobs."""

from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import IngestionJob, SourceRegistration
from app.ingestion.job_requests import JobRequest, generation_chunks, source_id
from app.ingestion.job_store import JobRun, now, require_run, transaction, utc
from app.ingestion.public_site import source_type
from app.ingestion.site_import import AUTHORIZATION_BASIS
from app.ingestion.site_index import IndexingError, UnexpectedChunks, WebsiteIndexer


@dataclass
class SourceWork:
    source_id: str
    url: str
    authorization: str
    action: str
    chunks: list[dict]
    generation: str | None
    registration: str


def source_record(db: Session, url: str, *, lock: bool = False) -> SourceRegistration | None:
    query = select(SourceRegistration).where(or_(SourceRegistration.source_id == source_id(url), SourceRegistration.url == url))
    if lock:
        query = query.with_for_update()
    rows = list(db.scalars(query))
    if len(rows) > 1:
        raise ValueError("Conflicting source registrations")
    source = rows[0] if rows else None
    if source and (source.source_id != source_id(url) or source.url != url
                   or source.source_type != source_type(url) or source.visibility != "public"):
        raise ValueError("Source identity or visibility conflicts with this public-site workflow")
    return source


def check_available(db: Session, source: SourceRegistration | None, run_id: str | None = None) -> None:
    if source and source.index_job_id and source.index_job_id != run_id:
        owner = db.get(IngestionJob, source.index_job_id)
        if owner and owner.status == "processing" and owner.lease_expires_at and utc(owner.lease_expires_at) > now():
            raise ValueError("Source is being processed by another job")


def preview(db: Session, request: JobRequest) -> dict:
    sources = []
    documents = {document.url: document for document in request.documents}
    for url in request.source_urls():
        source = source_record(db, url)
        check_available(db, source)
        document = documents.get(url)
        if document and source:
            if not source.is_active:
                raise ValueError("Source is disabled; import cannot reactivate it")
            if source.fetched_at and document.fetched_at < utc(source.fetched_at):
                raise ValueError("Source snapshot is older than the registered version")
        sources.append({
            "source_id": source_id(url), "url": url,
            "registration": "new" if source is None else "updated" if document and source.content_sha256 != document.content_sha256 else "existing",
            "chunks": len(generation_chunks(document, None)) if document else 0,
            "index_action": "unchecked" if document else "remove",
        })
    return {"status": "preview", "operation": request.operation, "sources": sources,
            "new_sources": sum(source["registration"] == "new" for source in sources) if documents else 0,
            "indexed_chunks": 0, "skipped_sources": 0, "skipped_chunks": 0}


def stage(sessions: sessionmaker[Session], run: JobRun, indexer: WebsiteIndexer) -> list[SourceWork]:
    work = []
    documents = {document.url: document for document in run.request.documents}
    with transaction(sessions) as db:
        job = require_run(db, run)
        # Stable locking order across overlapping batches.
        for url in sorted(run.request.source_urls()):
            source = source_record(db, url, lock=True)
            check_available(db, source, run.id)
            document = documents.get(url)
            registration = "new" if source is None else "existing"
            basis = source.authorization_basis if source else AUTHORIZATION_BASIS
            if document:
                if source and not source.is_active:
                    raise ValueError("Source is disabled; import cannot reactivate it")
                if source and source.fetched_at and document.fetched_at < utc(source.fetched_at):
                    raise ValueError("Source snapshot is older than the registered version")
                if (source and source.content_sha256 != document.content_sha256 and source.last_indexed_at
                    and utc(job.created_at) < utc(source.last_indexed_at)):
                    raise ValueError("Source version changed after this job was queued; submit a new import")
                if source and source.content_sha256 != document.content_sha256:
                    registration = "updated"
                check = bool(source and source.index_status == "ready" and source.content_sha256 == document.content_sha256)
                generation = source.index_generation if check else run.token
                chunks = generation_chunks(document, generation)
                action = "check" if check else "indexed"
                if source is None:
                    source = SourceRegistration(source_id=document.source_id, url=url, source_type=document.source_type,
                                                visibility="public", is_active=True, authorization_basis=basis,
                                                content_sha256=document.content_sha256)
                    db.add(source)
                source.content_sha256, source.fetched_at = document.content_sha256, document.fetched_at
                source.index_generation = generation
                source.index_status = "indexing"
            else:
                action, chunks, generation = "removed", [], None
                if source:
                    source.is_active, source.index_status = False, "removed"
            if source:
                source.index_job_id = run.id
            work.append(SourceWork(source_id(url), url, basis, action, chunks, generation, registration))
        job.result = {"sources": [{"source_id": item.source_id, "url": item.url, "index_action": item.action} for item in work]}
    # This commit is the retrieval barrier: indexing/removed sources are now hidden.
    return work


def check_ownership(sessions: sessionmaker[Session], run: JobRun, work: list[SourceWork]) -> None:
    with transaction(sessions) as db:
        require_run(db, run)
        for item in work:
            source = source_record(db, item.url, lock=True)
            if source is None:
                if item.action != "removed":
                    raise ValueError("Source disappeared during processing")
            elif (source.index_job_id != run.id or (item.action != "removed" and not source.is_active)
                  or (item.action == "removed" and source.is_active)
                  or (item.action != "removed" and (source.index_generation != item.generation
                      or source.index_status != "indexing" or source.content_sha256 != item.chunks[0]["content_sha256"]
                      or source.authorization_basis != item.authorization))):
                raise ValueError("Source permissions or job ownership changed during processing")


def process(sessions: sessionmaker[Session], run: JobRun, indexer: WebsiteIndexer) -> dict:
    work = stage(sessions, run, indexer)
    indexer.check_collection()
    check_ownership(sessions, run, work)
    documents = {document.url: document for document in run.request.documents}
    for item in work:
        if item.action == "check":
            try:
                current = indexer.source_is_current(item.chunks, item.authorization, generation=item.generation)
            except UnexpectedChunks:
                current = False
            check_ownership(sessions, run, work)
            if current:
                item.action = "skipped"
            else:
                with transaction(sessions) as db:
                    require_run(db, run)
                    source = source_record(db, item.url, lock=True)
                    if source is None or source.index_job_id != run.id or source.index_generation != item.generation:
                        raise ValueError("Source ownership changed before replacement")
                    source.index_generation = run.token
                item.action, item.generation = "indexed", run.token
                item.chunks = generation_chunks(documents[item.url], run.token)
    to_index = [chunk for item in work if item.action == "indexed" for chunk in item.chunks]
    if to_index:
        indexer.upsert_chunks(to_index, {item.source_id: item.authorization for item in work})
    deleted = 0
    for item in work:
        check_ownership(sessions, run, work)
        if item.action == "indexed" and not indexer.source_is_current(item.chunks, item.authorization, generation=item.generation):
            raise IndexingError("Replacement generation failed verification")
        keep = {chunk["id"] for chunk in item.chunks}
        obsolete = [point_id for point_id in indexer.source_point_ids(item.source_id) if point_id not in keep]
        # Use a snapshot of IDs, not a broad filter that could delete a later generation.
        check_ownership(sessions, run, work)
        indexer.delete_points(obsolete)
        deleted += len(obsolete)
        remaining = set(indexer.source_point_ids(item.source_id))
        if remaining != keep:
            raise IndexingError("Source cleanup did not reach the expected point set")
    result = {
        "status": "completed", "operation": run.request.operation,
        "new_sources": sum(item.registration == "new" for item in work) if run.request.operation == "import" else 0,
        "updated_sources": sum(item.registration == "updated" for item in work),
        "indexed_chunks": len(to_index), "skipped_sources": sum(item.action == "skipped" for item in work),
        "skipped_chunks": sum(len(item.chunks) for item in work if item.action == "skipped"),
        "removed_sources": len(work) if run.request.operation == "remove" else 0, "deleted_chunks": deleted,
        "sources": [{"source_id": item.source_id, "url": item.url, "registration": item.registration,
                     "chunks": len(item.chunks), "index_action": item.action} for item in work],
    }
    with transaction(sessions) as db:
        job = require_run(db, run)
        for item in work:
            source = source_record(db, item.url, lock=True)
            if source is None and item.action != "removed":
                raise ValueError("Source disappeared before publication")
            if source and (source.index_job_id != run.id or (item.action != "removed" and not source.is_active)
                           or (item.action == "removed" and source.is_active)
                           or (item.action != "removed" and (source.index_generation != item.generation
                               or source.index_status != "indexing" or source.content_sha256 != item.chunks[0]["content_sha256"]
                               or source.authorization_basis != item.authorization))):
                raise ValueError("Source ownership or permissions changed before publication")
            if source:
                source.last_synced_at = now()
                if item.action == "indexed":
                    source.last_indexed_at = now()
                if item.action != "removed":
                    source.index_status = "ready"
        job.status, job.result, job.finished_at = "completed", result, now()
    return result
