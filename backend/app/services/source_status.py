"""Exact source lifecycle metadata, with the existing role visibility policy."""

from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models import SourceRegistration, User
from app.retrieval.authorization import ALLOWED_VISIBILITIES
from app.tools.schemas import SourceStatus


def _utc(value: datetime | None) -> datetime | None:
    # SQLite test round trips drop tzinfo; production columns are timezone-aware.
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def get_source_status(db: Session, user: User, source_id: str) -> SourceStatus | None:
    allowed = ALLOWED_VISIBILITIES.get(user.role, set()) if user.is_active else set()
    if not allowed:
        return None
    # Authentication has already checked out this session's connection. Limits
    # are transaction-local and reset at rollback/close; no tool writes/commits.
    with db.no_autoflush:
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text("SET LOCAL statement_timeout = '2s'"))
            db.execute(text("SET LOCAL lock_timeout = '1s'"))
        source = db.scalar(select(SourceRegistration).where(
            SourceRegistration.source_id == source_id,
            SourceRegistration.visibility.in_(allowed),
        ).limit(1))
        if source is None:
            return None
        return SourceStatus(
            observed_at=datetime.now(timezone.utc), source_id=source.source_id,
            title=source.title, url=source.url, visibility=source.visibility,
            is_active=source.is_active, index_status=source.index_status,
            retrieval_ready=source.is_active and source.index_status == "ready",
            fetched_at=_utc(source.fetched_at), last_indexed_at=_utc(source.last_indexed_at),
            last_synced_at=_utc(source.last_synced_at),
        )
