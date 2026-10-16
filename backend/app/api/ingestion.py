"""Internal URL/file ingestion, source access, and redacted job status."""

from hashlib import sha256
import threading
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import Response
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.requests import Request as StarletteRequest

from app.auth.dependencies import get_current_user
from app.api.request_limits import bounded_body
from app.core.config import Settings
from app.db.models import IngestionJob, SourceRegistration, User
from app.db.session import get_db
from app.ingestion.access import can_read
from app.ingestion.documents import FILE_PREFIX
from app.ingestion.extraction import ExtractionError, storage_path
from app.ingestion.extract_worker import MAX_FILE_BYTES
from app.ingestion.job_store import job_view
from app.retrieval.authorization import ALLOWED_VISIBILITIES
from app.schemas.ingestion import FileSubmission, URLSubmission
from app.services import ingestion as service

router = APIRouter(prefix="/api/v1/ingestion", tags=["ingestion"])
DB = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


def get_settings() -> Settings:
    return Settings()


Config = Annotated[Settings, Depends(get_settings)]
_processing_slot = threading.BoundedSemaphore(1)


def process_submission(function, sessions, settings, user_id, args):
    # One active ingestion request per API process avoids concurrent bounded
    # parser processes exhausting a small local machine. Do not build a queue.
    if not _processing_slot.acquire(blocking=False):
        raise HTTPException(429, "Ingestion is busy; try again shortly", headers={"Retry-After": "5"})
    try:
        return function(sessions, settings, user_id, *args)
    finally:
        _processing_slot.release()


async def call(function, db: Session, settings: Settings, user: User, *args) -> dict:
    try:
        return await run_in_threadpool(process_submission, function, sessionmaker(bind=db.get_bind()), settings, user.id, args)
    except ExtractionError as exc:
        raise HTTPException(400, str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(400, "Invalid extracted document") from exc
    except (SQLAlchemyError, OSError) as exc:
        raise HTTPException(503, "Ingestion storage or database unavailable; inspect job status before retrying") from exc


@router.post("/urls", openapi_extra={"requestBody": {"required": True, "content": {
    "application/json": {"schema": URLSubmission.model_json_schema()}
}}})
async def import_url(request: Request, user: CurrentUser, db: DB, settings: Config) -> dict:
    try:
        raw = await bounded_body(request, 4096)
        submission = URLSubmission.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(422, "Invalid URL submission") from exc
    except TimeoutError as exc:
        raise HTTPException(408, "Request body timed out") from exc
    return await call(service.import_url, db, settings, user, submission)


@router.post("/files", openapi_extra={"requestBody": {"required": True, "content": {
    "multipart/form-data": {"schema": {"type": "object", "required": ["file"], "properties": {
        "file": {"type": "string", "format": "binary"}, **FileSubmission.model_json_schema()["properties"],
    }}}
}}})
async def upload(request: Request, user: CurrentUser, db: DB, settings: Config) -> dict:
    if request.headers.get("content-type", "").split(";")[0] != "multipart/form-data":
        raise HTTPException(415, "Use multipart/form-data with one file")
    try:
        # Read a bounded body only after authentication; this also bounds file
        # bytes, which multipart's max_part_size alone does not do.
        raw = await bounded_body(request, MAX_FILE_BYTES + 64 * 1024)
        delivered = False

        async def receive():
            nonlocal delivered
            if delivered:
                return {"type": "http.request", "body": b"", "more_body": False}
            delivered = True
            return {"type": "http.request", "body": raw, "more_body": False}

        parsed = StarletteRequest(request.scope, receive)
        async with parsed.form(max_files=1, max_fields=3, max_part_size=2048) as form:
            if any(name not in {"file", "visibility", "title", "source_id"} for name in form) or len(form.multi_items()) != len(form):
                raise HTTPException(422, "Unknown or repeated form fields")
            file = form.get("file")
            if not isinstance(file, UploadFile) or not file.filename:
                raise HTTPException(422, "Provide one file")
            metadata = FileSubmission.model_validate({key: value for key, value in form.items() if key != "file"})
            content = await file.read(MAX_FILE_BYTES + 1)
            if len(content) > MAX_FILE_BYTES:
                raise HTTPException(413, "File exceeds the 5 MiB limit")
            return await call(service.upload, db, settings, user, content, file.filename, metadata)
    except ValidationError as exc:
        fields = sorted({str(error["loc"][0]) for error in exc.errors(include_input=False) if error["loc"]})
        raise HTTPException(422, "Invalid file metadata: " + ", ".join(fields)) from exc
    except TimeoutError as exc:
        raise HTTPException(408, "Request body timed out") from exc


@router.get("/jobs")
def jobs(user: CurrentUser, db: DB, limit: int = Query(10, ge=1, le=50)) -> list[dict]:
    query = select(IngestionJob).order_by(IngestionJob.created_at.desc(), IngestionJob.id).limit(limit)
    if user.role != "admin":
        query = query.where(IngestionJob.submitted_by_user_id == user.id)
    result = []
    for job in db.scalars(query):
        try:
            result.append(job_view(service.accessible_job(db, user, job.id)))
        except HTTPException:
            continue
    return result


@router.get("/jobs/{job_id}")
def job(job_id: UUID, user: CurrentUser, db: DB) -> dict:
    return job_view(service.accessible_job(db, user, str(job_id)))


@router.post("/jobs/{job_id}/retry")
async def retry(job_id: UUID, user: CurrentUser, db: DB, settings: Config) -> dict:
    return await call(service.retry, db, settings, user, str(job_id))


@router.get("/sources")
def sources(user: CurrentUser, db: DB, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0, le=10000)) -> list[dict]:
    query = select(SourceRegistration).where(SourceRegistration.visibility.in_(ALLOWED_VISIBILITIES[user.role]))
    query = query.order_by(SourceRegistration.created_at.desc(), SourceRegistration.source_id).offset(offset).limit(limit)
    return [service.source_view(source) for source in db.scalars(query)]


@router.delete("/sources/{identity}")
async def remove(identity: Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")], user: CurrentUser, db: DB, settings: Config) -> dict:
    return await call(service.remove, db, settings, user, identity)


@router.get("/files/{file_id}")
def content(file_id: UUID, user: CurrentUser, db: DB, settings: Config) -> Response:
    url = FILE_PREFIX + str(file_id)
    source = db.scalar(select(SourceRegistration).where(SourceRegistration.url == url))
    if source is None or not source.is_active or source.index_status != "ready" or not can_read(user, source):
        raise HTTPException(404, "File not found")
    try:
        if not isinstance(source.storage_key, str):
            raise ValueError("No stored original")
        path = storage_path(settings, source.storage_key)
        with path.open("rb") as stream:
            raw = stream.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES or sha256(raw).hexdigest() != source.file_sha256:
            raise ValueError("Stored content failed integrity check")
    except (OSError, ValueError, TypeError) as exc:
        raise HTTPException(503, "Stored source content unavailable") from exc
    # Attachment plus sandbox/nosniff avoids rendering untrusted active content.
    return Response(raw, media_type=source.media_type, headers={
        "Content-Disposition": "attachment", "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store",
        "Content-Security-Policy": "sandbox; default-src 'none'",
    })
