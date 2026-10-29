"""Single-process PostgreSQL-backed ingestion runner; no broker required."""

import logging
import signal
import time

import httpx
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.session import SessionLocal
from app.ingestion.job_runner import JobFailed, run_job
from app.ingestion.job_store import next_job
from app.ingestion.site_index import WebsiteIndexer

logger = logging.getLogger(__name__)
POLL_SECONDS = 1.0


def process_one(sessions: sessionmaker[Session], settings: Settings, client: httpx.Client) -> bool:
    candidate = next_job(sessions)
    if candidate is None:
        return False
    job_id, retry = candidate
    try:
        run_job(sessions, job_id, WebsiteIndexer(settings, client), retry=retry)
    except (JobFailed, ValueError) as exc:
        # Failed jobs stay visible through the authenticated job endpoint.
        logger.warning("ingestion_worker_job_failed job_id=%s reason=%s", job_id, type(exc).__name__)
    return True


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = Settings()
    if settings.ingestion_runner != "worker":
        raise RuntimeError("Set SARDARS_INGESTION_RUNNER=worker for the dedicated runner")
    stopping = False

    def stop(_signum, _frame) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with httpx.Client(follow_redirects=False) as client:
        while not stopping:
            try:
                if not process_one(SessionLocal, settings, client):
                    time.sleep(POLL_SECONDS)
            except Exception:
                logger.exception("ingestion_worker_loop_error")
                time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
