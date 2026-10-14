"""Authenticated submissions reuse durable source synchronization."""

from hashlib import sha256
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import HTTPException
import httpx
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.models import IngestionJob, SourceRegistration, User
from app.ingestion.access import can_manage, can_read, check_submission
from app.ingestion.documents import FILE_PREFIX, SuppliedDocument, file_url
from app.ingestion.extraction import extract_file, extract_url, file_format, storage_path, store_original
from app.ingestion.job_requests import JobRequest, source_id
from app.ingestion.job_runner import JobFailed, run_job
from app.ingestion.job_store import enqueue, now
from app.ingestion.public_site import source_type
from app.ingestion.site_index import WebsiteIndexer
from app.schemas.ingestion import FileSubmission, URLSubmission


def load_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None or not user.is_active or user.role not in {"staff", "admin"}:
        raise HTTPException(401, "Authentication required")
    return user


def manageable(db: Session, user: User, identity: str) -> SourceRegistration:
    source = db.get(SourceRegistration, identity)
    if source is None or not can_manage(user, source):
        raise HTTPException(404, "Source not found")
    return source


def preflight(sessions: sessionmaker[Session], user_id: int, url: str, visibility: str, kind: str) -> None:
    with sessions() as db:
        user = load_user(db, user_id)
        source = db.get(SourceRegistration, source_id(url))
        try:
            check_submission(user, source, visibility)
        except ValueError as exc:
            raise HTTPException(403, "Source submission is not permitted") from exc
        if source and (not source.is_active or source.source_type != kind):
            raise HTTPException(409, "Source is disabled or its format conflicts with this import")


def execute(sessions: sessionmaker[Session], settings: Settings, job_id: str, *, retry: bool = False) -> dict:
    try:
        with httpx.Client(follow_redirects=False) as client:
            return run_job(sessions, job_id, WebsiteIndexer(settings, client), retry=retry)
    except JobFailed as exc:
        raise HTTPException(503, {"job_id": exc.job_id, "status": "failed", "error": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(409, {"job_id": job_id, "error": str(exc)}) from exc


def submit(sessions: sessionmaker[Session], settings: Settings, user_id: int, *, raw: bytes, text: str,
           title: str, url: str, kind: str, visibility: str, filename: str, media_type: str) -> dict:
    preflight(sessions, user_id, url, visibility, kind)
    key, checksum = store_original(settings, raw)
    job_id = None
    try:
        doc = SuppliedDocument(
            source_id=source_id(url), url=url, source_type=kind, visibility=visibility,
            title=title, text=text, fetched_at=now(), content_sha256=sha256(text.encode()).hexdigest(),
            storage_key=key, original_filename=filename, media_type=media_type, file_sha256=checksum,
        )
        job_id = enqueue(sessions, JobRequest(operation="import", scope="internal", documents=[doc]), submitted_by_user_id=user_id)
    finally:
        if job_id is None:
            storage_path(settings, key).unlink(missing_ok=True)
    return execute(sessions, settings, job_id)


def upload(sessions: sessionmaker[Session], settings: Settings, user_id: int, raw: bytes,
           filename: str, metadata: FileSubmission) -> dict:
    kind, media_type = file_format(filename)
    url = FILE_PREFIX + str(uuid4())
    if metadata.source_id:
        with sessions() as db:
            source = manageable(db, load_user(db, user_id), metadata.source_id)
            if not file_url(source.url):
                raise HTTPException(409, "Only an uploaded source can be updated with a file")
            url = source.url
    preflight(sessions, user_id, url, metadata.visibility, kind)
    text = extract_file(raw, kind)
    return submit(sessions, settings, user_id, raw=raw, text=text, title=metadata.title or filename,
                  url=url, kind=kind, visibility=metadata.visibility, filename=filename, media_type=media_type)


def import_url(sessions: sessionmaker[Session], settings: Settings, user_id: int, submission: URLSubmission) -> dict:
    host = urlsplit(submission.url).hostname
    if host not in settings.ingestion_url_hosts:
        raise HTTPException(400, "URL host is not configured for ingestion")
    if host == "sardarandco.com" and source_type(submission.url) is None:
        raise HTTPException(400, "Select a descriptive Sardars page, article, or product URL")
    kind = source_type(submission.url) or "web"
    preflight(sessions, user_id, submission.url, submission.visibility, kind)
    raw, title, text = extract_url(submission.url, settings)
    return submit(sessions, settings, user_id, raw=raw, text=text, title=title, url=submission.url,
                  kind=kind, visibility=submission.visibility, filename="page.html", media_type="text/html")


def accessible_job(db: Session, user: User, job_id: str) -> IngestionJob:
    job = db.get(IngestionJob, job_id)
    if job is None or (user.role != "admin" and job.submitted_by_user_id != user.id):
        raise HTTPException(404, "Job not found")
    # Current source visibility can revoke access to a previously owned job.
    try:
        request = JobRequest.model_validate(job.request)
    except ValueError:
        if user.role != "admin":
            raise HTTPException(404, "Job not found") from None
        return job
    for url in request.source_urls():
        source = db.get(SourceRegistration, source_id(url))
        if (source and not can_read(user, source)) or (user.role != "admin" and any(
            doc.visibility == "admin" for doc in request.documents)):
            raise HTTPException(404, "Job not found")
    return job


def retry(sessions: sessionmaker[Session], settings: Settings, user_id: int, job_id: str) -> dict:
    with sessions() as db:
        user = load_user(db, user_id)
        job = accessible_job(db, user, job_id)
        # The original submitter must still be allowed to run the snapshot;
        # run_job rechecks that identity throughout processing.
        try:
            request = JobRequest.model_validate(job.request)
        except ValueError as exc:
            raise HTTPException(409, "Stored job is invalid; submit a new import") from exc
        for url in request.source_urls():
            source = db.get(SourceRegistration, source_id(url))
            if source and not can_manage(user, source):
                raise HTTPException(404, "Job not found")
        if request.scope != "internal":
            raise HTTPException(409, "Use the local CLI to retry local-operator jobs")
    return execute(sessions, settings, job_id, retry=True)


def remove(sessions: sessionmaker[Session], settings: Settings, user_id: int, identity: str) -> dict:
    with sessions() as db:
        source = manageable(db, load_user(db, user_id), identity)
        url = source.url
    job_id = enqueue(sessions, JobRequest(operation="remove", scope="internal", urls=[url]), submitted_by_user_id=user_id)
    return execute(sessions, settings, job_id)


def source_view(source: SourceRegistration) -> dict:
    return {"source_id": source.source_id, "title": source.title, "url": source.url,
            "source_type": source.source_type, "visibility": source.visibility, "active": source.is_active,
            "index_status": source.index_status, "job_id": source.index_job_id,
            "fetched_at": source.fetched_at, "last_indexed_at": source.last_indexed_at,
            "last_synced_at": source.last_synced_at, "registered_by_user_id": source.registered_by_user_id}
