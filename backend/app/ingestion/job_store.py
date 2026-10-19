"""Durable job admission, bounded claims, fencing, and redacted status views."""

from dataclasses import dataclass
from contextlib import contextmanager
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import IngestionJob, SourceRegistration
from app.ingestion.job_requests import JobRequest

MAX_ATTEMPTS = 3


@contextmanager
def transaction(sessions: sessionmaker[Session]) -> Iterator[Session]:
    with sessions.begin() as db:
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text("SET LOCAL lock_timeout = '5s'"))
            db.execute(text("SET LOCAL statement_timeout = '10s'"))
        yield db


def now() -> datetime:
    return datetime.now(timezone.utc)


def utc(value: datetime) -> datetime:
    # SQLite's test dialect omits timezone information on round-trip.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


@dataclass(frozen=True)
class JobRun:
    id: str
    token: str
    attempt: int
    request: JobRequest


def enqueue(sessions: sessionmaker[Session], request: JobRequest, *, submitted_by_user_id: int | None = None,
            job_id: str | None = None, parent_job_id: str | None = None) -> str:
    if request.scope == "internal" and submitted_by_user_id is None:
        raise ValueError("Internal ingestion requires an authenticated submitter")
    job_id = str(UUID(job_id)) if job_id else str(uuid4())
    snapshot = request.snapshot()
    # Validate the serialized form as well; a retry never trusts edited DB JSON.
    JobRequest.model_validate(snapshot)
    with transaction(sessions) as db:
        existing = db.get(IngestionJob, job_id)
        if existing is not None:
            if (existing.request != snapshot or existing.operation != request.operation
                or existing.submitted_by_user_id != submitted_by_user_id or existing.parent_job_id != parent_job_id):
                raise ValueError("Job identity conflicts with its saved snapshot")
            return job_id
        db.add(IngestionJob(id=job_id, operation=request.operation, request=snapshot, status="pending", attempts=0,
                            created_at=now(), submitted_by_user_id=submitted_by_user_id, parent_job_id=parent_job_id))
    return job_id


def claim(sessions: sessionmaker[Session], job_id: str, budget: float, *, retry: bool = False) -> JobRun:
    exhausted = False
    invalid = False
    with transaction(sessions) as db:
        job = db.scalar(select(IngestionJob).where(IngestionJob.id == job_id).with_for_update())
        if job is None:
            raise ValueError("Job not found")
        expired = job.status == "processing" and job.lease_expires_at is not None and utc(job.lease_expires_at) <= now()
        if job.status == "completed" or (job.status != "pending" and not retry) or (job.status == "processing" and not expired):
            raise ValueError("Job cannot be claimed; retry only failed, pending, or expired jobs")
        if job.attempts >= MAX_ATTEMPTS:
            if expired:
                job.status, job.error_code, job.error_message = "failed", "retry_limit", "Retry limit reached"
                job.finished_at = now()
                for source in db.scalars(select(SourceRegistration).where(SourceRegistration.index_job_id == job_id)):
                    if source.index_status == "indexing":
                        source.index_status = "failed"
            exhausted = True
        else:
            try:
                request = JobRequest.model_validate(job.request)
                request.snapshot()
                if request.operation != job.operation:
                    raise ValueError("Operation mismatch")
            except ValueError:
                invalid = True
                job.status, job.error_code, job.error_message = "failed", "invalid_snapshot", "Invalid stored source snapshot"
                job.attempts += 1
                job.finished_at = now()
                for source in db.scalars(select(SourceRegistration).where(SourceRegistration.index_job_id == job_id)):
                    if source.index_status == "indexing":
                        source.index_status = "failed"
            else:
                token = str(uuid4())
                job.status, job.run_token = "processing", token
                job.attempts += 1
                job.started_at, job.finished_at = now(), None
                # Allows bounded socket teardown after the index processing budget.
                job.lease_expires_at = now() + timedelta(seconds=2 * budget + 60)
                job.error_code, job.error_message = None, None
                if request.operation != "crawl":
                    job.result = None
                run = JobRun(job.id, token, job.attempts, request)
    if exhausted:
        raise ValueError("Retry limit reached")
    if invalid:
        raise ValueError("Invalid stored source snapshot")
    return run


def require_run(db: Session, run: JobRun) -> IngestionJob:
    job = db.scalar(select(IngestionJob).where(IngestionJob.id == run.id).with_for_update())
    if (job is None or job.status != "processing" or job.run_token != run.token
        or job.lease_expires_at is None or utc(job.lease_expires_at) <= now()):
        raise ValueError("Job ownership expired or was replaced")
    return job


def fail(sessions: sessionmaker[Session], run: JobRun, code: str, message: str) -> None:
    with transaction(sessions) as db:
        job = db.scalar(select(IngestionJob).where(IngestionJob.id == run.id).with_for_update())
        if job is None or job.run_token != run.token or job.status != "processing":
            return
        job.status, job.error_code, job.error_message = "failed", code, message
        job.finished_at = now()
        for source in db.scalars(select(SourceRegistration).where(SourceRegistration.index_job_id == run.id).with_for_update()):
            if source.index_status == "indexing":
                source.index_status = "failed"


def requeue(sessions: sessionmaker[Session], job_id: str) -> None:
    """Explicitly retry a failed job without changing its saved input."""
    with transaction(sessions) as db:
        job = db.scalar(select(IngestionJob).where(IngestionJob.id == job_id).with_for_update())
        if job is None or job.attempts >= MAX_ATTEMPTS:
            raise ValueError("Job not found or retry limit reached")
        expired = job.status == "processing" and job.lease_expires_at and utc(job.lease_expires_at) <= now()
        if job.status != "failed" and not expired:
            raise ValueError("Only failed or expired jobs can be retried")
        job.status, job.run_token, job.lease_expires_at = "pending", None, None
        job.error_code, job.error_message, job.finished_at = None, None, None


def next_job(sessions: sessionmaker[Session]) -> tuple[str, bool] | None:
    """Read the oldest runnable ID; claim() remains the concurrency fence."""
    with sessions() as db:
        job = db.scalar(select(IngestionJob).where(or_(
            IngestionJob.status == "pending",
            (IngestionJob.status == "processing") & (IngestionJob.lease_expires_at <= now()),
        )).order_by(IngestionJob.created_at, IngestionJob.id).limit(1))
        return (job.id, job.status == "processing") if job else None


def job_view(job: IngestionJob) -> dict:
    """Never return snapshots/document text, credentials, or worker tokens."""
    result = job.result
    if job.operation == "crawl" and isinstance(result, dict):
        result = {key: value for key, value in result.items() if key != "urls"}
    return {
        "job_id": job.id, "operation": job.operation, "status": job.status, "parent_job_id": job.parent_job_id,
        "attempts": job.attempts, "max_attempts": MAX_ATTEMPTS,
        "created_at": utc(job.created_at).isoformat(),
        "started_at": utc(job.started_at).isoformat() if job.started_at else None,
        "finished_at": utc(job.finished_at).isoformat() if job.finished_at else None,
        "lease_expired": bool(job.status == "processing" and job.lease_expires_at and utc(job.lease_expires_at) <= now()),
        "error_code": job.error_code, "error": job.error_message, "result": result,
    }
