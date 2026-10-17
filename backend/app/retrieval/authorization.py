"""Check indexed points against the source registry before using their text."""

from hashlib import sha256

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models import SourceRegistration


ALLOWED_VISIBILITIES = {
    "admin": {"public", "staff", "admin"},
    "staff": {"public", "staff"},
}


def authorized_points(db: Session, role: str, points: list[dict]) -> list[dict]:
    """Fail closed on unknown, disabled, or mismatched source metadata."""
    allowed = ALLOWED_VISIBILITIES.get(role, set())
    if not allowed:
        return []

    ids = {
        source_id
        for point in points
        if isinstance(point.get("payload"), dict)
        if isinstance(source_id := point["payload"].get("source_id"), str)
    }
    if not ids:
        return []
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SET LOCAL statement_timeout = '2s'"))
        db.execute(text("SET LOCAL lock_timeout = '1s'"))
    registrations = {
        source.source_id: source
        for source in db.scalars(
            select(SourceRegistration).where(SourceRegistration.source_id.in_(ids))
        )
    }

    result: list[dict] = []
    for point in points:
        payload = point.get("payload")
        if not isinstance(payload, dict):
            continue
        source_id = payload.get("source_id")
        if not isinstance(source_id, str):
            continue
        source = registrations.get(source_id)
        url = payload.get("url")
        if (
            source is None
            or not source.is_active
            or source.index_status != "ready"
            or (source.index_generation is not None and source.index_generation != payload.get("index_generation"))
            or source.visibility not in allowed
            or source.visibility != payload.get("visibility")
            or source.url != url
            or source.source_type != payload.get("source_type")
            or source.content_sha256 != payload.get("content_sha256")
            or not isinstance(url, str)
            or sha256(url.encode()).hexdigest() != source.source_id
            or payload.get("review_status") != "approved"
            or payload.get("prototype_only") is not False
        ):
            continue
        result.append(point)
    return result
