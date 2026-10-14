"""Phase 5, Step 3A: import saved website records, skipping verified indexed content.

Run as a trusted local operator with the project's database/service settings.
Sources are limited to owner-authorized public Sardars descriptive URLs.
"""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
import time

import httpx
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.ingestion.prepare_site import load_selected_documents
from app.ingestion.site_import import apply_import, plan_import
from app.ingestion.site_index import IndexingError, WebsiteIndexer
from app.retrieval.seed_config import COLLECTION, MODEL


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Original saved crawler JSONL file")
    parser.add_argument("--url", action="append", required=True, help="Exact URL; repeat for up to 10 sources")
    parser.add_argument("--apply", action="store_true", help="Register and index; default is registry preview only")
    arguments = parser.parse_args(argv)
    started = time.monotonic()
    try:
        documents = load_selected_documents(arguments.input, arguments.url)
        settings = Settings()
        # Lazy import keeps --help usable without a configured database.
        from app.db.session import SessionLocal

        if arguments.apply:
            with httpx.Client(follow_redirects=False) as client:
                indexer = WebsiteIndexer(settings, client)
                with SessionLocal.begin() as db:
                    result = apply_import(db, documents, indexer)
            # Publish completion only after the PostgreSQL commit succeeded.
        else:
            with SessionLocal() as db:
                result = plan_import(db, documents)
    except ValidationError:
        error = "Invalid document or local configuration; check metadata and required environment settings"
    except SQLAlchemyError:
        error = "Database unavailable or source registration could not be committed"
    except (IndexingError, OSError, ValueError) as exc:
        error = str(exc)
    else:
        print(json.dumps({
            "phase": 5, "step": 3, "checkpoint": "3A",
            "collection": COLLECTION, "embedding_model": MODEL,
            **asdict(result), "duration_ms": round((time.monotonic() - started) * 1000, 1),
        }, indent=2))
        return

    print(json.dumps({
        "phase": 5, "step": 3, "checkpoint": "3A", "status": "failed", "error": error,
    }), file=sys.stderr)
    raise SystemExit(1)


if __name__ == "__main__":
    main()
