"""Inspect local ingestion job metadata without printing document snapshots."""

import argparse
import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from pydantic import ValidationError

from app.db.models import IngestionJob
from app.ingestion.job_store import job_view


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=UUID, help="Inspect one job")
    parser.add_argument("--limit", type=int, default=10, help="Recent jobs, between 1 and 50")
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 50:
        parser.error("Limit must be between 1 and 50")
    try:
        from app.db.session import SessionLocal
        with SessionLocal() as db:
            query = select(IngestionJob).order_by(IngestionJob.created_at.desc(), IngestionJob.id).limit(args.limit)
            if args.job:
                query = query.where(IngestionJob.id == str(args.job))
            jobs = [job_view(job) for job in db.scalars(query)]
    except SQLAlchemyError:
        parser.error("Database unavailable; apply migrations before inspecting jobs")
    except ValidationError:
        parser.error("Invalid local database configuration")
    print(json.dumps(jobs, indent=2))


if __name__ == "__main__":
    main()
