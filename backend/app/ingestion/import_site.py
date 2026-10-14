"""Phase 5, Step 3B/3C: durable public-site synchronization and explicit retries.

Run as a trusted local operator with the project's database/service settings.
Sources are limited to owner-authorized public Sardars descriptive URLs.
"""

import argparse
import json
from pathlib import Path
import sys
import time
from uuid import UUID

import httpx
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.ingestion.job_requests import JobRequest
from app.ingestion.job_runner import JobFailed, run_job
from app.ingestion.job_store import enqueue
from app.ingestion.prepare_site import load_selected_documents
from app.ingestion.site_index import WebsiteIndexer
from app.ingestion.sync_sources import preview
from app.retrieval.seed_config import COLLECTION, MODEL


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Original saved crawler JSONL file for imports")
    parser.add_argument("--url", action="append", help="Exact URL; repeat for up to ten sources")
    parser.add_argument("--remove", action="store_true", help="Disable selected sources and remove their vectors")
    parser.add_argument("--retry", type=UUID, help="Retry a failed/pending/expired job using its saved snapshot")
    parser.add_argument("--apply", action="store_true", help="Apply changes; default is registry-only preview")
    arguments = parser.parse_args(argv)
    if arguments.retry:
        if not arguments.apply or arguments.input or arguments.url or arguments.remove:
            parser.error("Use --retry JOB_ID --apply without other source arguments")
    elif not arguments.url or (arguments.remove and arguments.input) or (not arguments.remove and not arguments.input):
        parser.error("Imports require --input/--url; removals require --remove/--url")
    started, job_id = time.monotonic(), None
    try:
        request = None
        if not arguments.retry:
            request = JobRequest(operation="remove", urls=arguments.url) if arguments.remove else JobRequest(
                operation="import", documents=load_selected_documents(arguments.input, arguments.url),
            )
        settings = Settings()
        # Lazy import keeps --help usable without a configured database.
        from app.db.session import SessionLocal

        if arguments.apply:
            job_id = str(arguments.retry) if arguments.retry else enqueue(SessionLocal, request)
            with httpx.Client(follow_redirects=False) as client:
                result = run_job(SessionLocal, job_id, WebsiteIndexer(settings, client), retry=bool(arguments.retry))
        else:
            with SessionLocal() as db:
                result = preview(db, request)
    except JobFailed as exc:
        job_id, error = exc.job_id, str(exc)
    except ValidationError:
        error = "Invalid document or local configuration; check metadata and required environment settings"
    except SQLAlchemyError:
        error = "Database unavailable; apply migrations and inspect job status after recovery"
    except (OSError, ValueError) as exc:
        error = str(exc)
    else:
        print(json.dumps({
            "phase": 5, "step": 3, "checkpoint": "3B/3C",
            "collection": COLLECTION, "embedding_model": MODEL,
            **result, "duration_ms": round((time.monotonic() - started) * 1000, 1),
        }, indent=2))
        return

    print(json.dumps({
        "phase": 5, "step": 3, "checkpoint": "3B/3C", "status": "failed", "job_id": job_id, "error": error,
    }), file=sys.stderr)
    raise SystemExit(1)


if __name__ == "__main__":
    main()
