"""Run one durable job synchronously; retries are explicit and limited."""

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from pydantic import ValidationError

from app.ingestion.job_store import claim, fail
from app.ingestion.site_index import IndexingError, WebsiteIndexer
from app.ingestion.sync_sources import process


class JobFailed(RuntimeError):
    def __init__(self, job_id: str, message: str):
        super().__init__(message)
        self.job_id = job_id


def run_job(sessions: sessionmaker[Session], job_id: str, indexer: WebsiteIndexer, *, retry: bool = False) -> dict:
    run = claim(sessions, job_id, indexer.settings.import_timeout_seconds, retry=retry)
    try:
        result = process(sessions, run, indexer)
    except Exception as exc:
        if isinstance(exc, ValidationError):
            code, message = "invalid_input", "Invalid stored source snapshot"
        elif isinstance(exc, SQLAlchemyError):
            code, message = "database_error", "Database unavailable during ingestion"
        elif isinstance(exc, IndexingError):
            code, message = "index_error", str(exc)
        elif isinstance(exc, ValueError):
            code, message = "source_conflict", str(exc)
        else:
            code, message = "internal_error", "Ingestion failed; inspect the job status and retry"
        try:
            fail(sessions, run, code, message)
        except SQLAlchemyError:
            # The durable processing lease allows recovery after a DB outage.
            pass
        raise JobFailed(job_id, message) from exc
    except KeyboardInterrupt:
        fail(sessions, run, "interrupted", "Operator interrupted ingestion")
        raise
    return {**result, "job_id": job_id, "attempts": run.attempt}
