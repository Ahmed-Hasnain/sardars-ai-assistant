"""Run one durable job synchronously; retries are explicit and limited."""

import logging
import time

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from pydantic import ValidationError

from app.ingestion.extraction import ExtractionError
from app.ingestion.job_store import claim, extend_lease, fail
from app.ingestion.materialize import materialize
from app.ingestion.site_index import IndexingError, WebsiteIndexer
from app.ingestion.sitemap_jobs import run_crawl
from app.ingestion.sync_sources import process
from app.ingestion.site_documents import MAX_DOCUMENT_CHARS, MAX_DOCUMENT_WORDS

logger = logging.getLogger(__name__)


class JobFailed(RuntimeError):
    def __init__(self, job_id: str, message: str):
        super().__init__(message)
        self.job_id = job_id


def run_job(sessions: sessionmaker[Session], job_id: str, indexer: WebsiteIndexer, *, retry: bool = False) -> dict:
    started = time.monotonic()
    run = claim(sessions, job_id, indexer.settings.import_timeout_seconds, retry=retry)
    logger.info("ingestion_started job_id=%s attempt=%s operation=%s", job_id, run.attempt, run.request.operation)
    try:
        if run.request.operation == "crawl":
            result = run_crawl(sessions, run, indexer.settings)
        else:
            run = materialize(sessions, run, indexer.settings)
            if (indexer.settings.ingestion_runner == "worker"
                and any(
                    document.source_type in {"text", "markdown"}
                    and (len(document.text) > MAX_DOCUMENT_CHARS
                         or len(document.text.split()) > MAX_DOCUMENT_WORDS)
                    for document in run.request.documents
                )):
                budget = indexer.settings.large_text_import_timeout_seconds
                extend_lease(sessions, run, budget)
                indexer.extend_deadline(budget)
            result = process(sessions, run, indexer)
    except Exception as exc:
        if isinstance(exc, ExtractionError):
            code, message = "extraction_error", str(exc)
        elif isinstance(exc, ValidationError):
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
        logger.warning("ingestion_failed job_id=%s attempt=%s code=%s duration_ms=%.1f", job_id, run.attempt, code, (time.monotonic() - started) * 1000)
        raise JobFailed(job_id, message) from exc
    except KeyboardInterrupt:
        fail(sessions, run, "interrupted", "Operator interrupted ingestion")
        raise
    logger.info("ingestion_completed job_id=%s attempt=%s indexed=%s skipped=%s deleted=%s duration_ms=%.1f", job_id, run.attempt, result["indexed_chunks"], result["skipped_chunks"], result["deleted_chunks"], (time.monotonic() - started) * 1000)
    return {**result, "job_id": job_id, "attempts": run.attempt}
