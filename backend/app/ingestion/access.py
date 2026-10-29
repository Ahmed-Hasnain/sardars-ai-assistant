"""Source management rights are enforced by application code, never the model."""

from sqlalchemy.orm import Session

from app.db.models import IngestionJob, SourceRegistration, User
from app.retrieval.authorization import ALLOWED_VISIBILITIES


def actor(db: Session, job: IngestionJob) -> User:
    user = db.get(User, job.submitted_by_user_id) if job.submitted_by_user_id else None
    if user is None or not user.is_active or user.role not in ALLOWED_VISIBILITIES:
        raise ValueError("Ingestion submitter is no longer authorized")
    if job.parent_job_id is not None and user.role != "admin":
        raise ValueError("Sitemap page submitter is no longer an admin")
    return user


def can_read(user: User, source: SourceRegistration) -> bool:
    return user.is_active and source.visibility in ALLOWED_VISIBILITIES.get(user.role, set())


def can_manage(user: User, source: SourceRegistration) -> bool:
    return can_read(user, source) and (user.role == "admin" or (
        source.registered_by_user_id == user.id and source.visibility == "staff"))


def check_submission(user: User, source: SourceRegistration | None, visibility: str | None = None) -> None:
    if source is not None and not can_manage(user, source):
        raise ValueError("Source management access denied")
    if visibility is not None:
        if visibility not in ALLOWED_VISIBILITIES.get(user.role, set()) or (user.role == "staff" and visibility != "staff"):
            raise ValueError("Source visibility access denied")
        if source is not None and source.visibility != visibility:
            raise ValueError("An import cannot change existing source visibility")
