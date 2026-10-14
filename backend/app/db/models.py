"""Users and revocable login sessions for the internal prototype."""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('admin', 'staff')", name="ck_users_role"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LoginSession(Base):
    __tablename__ = "login_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    expires_at_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        CheckConstraint("operation IN ('import', 'remove')", name="ck_ingestion_jobs_operation"),
        CheckConstraint("status IN ('pending', 'processing', 'completed', 'failed')", name="ck_ingestion_jobs_status"),
        CheckConstraint("attempts >= 0 AND attempts <= 3", name="ck_ingestion_jobs_attempts"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    request: Mapped[dict] = mapped_column(JSON, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    run_token: Mapped[str | None] = mapped_column(String(36))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(32))
    error_message: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SourceRegistration(Base):
    """PostgreSQL's authoritative permission record for an indexed source."""

    __tablename__ = "source_registrations"
    __table_args__ = (
        CheckConstraint("visibility IN ('public', 'staff', 'admin')", name="ck_source_registrations_visibility"),
        CheckConstraint("index_status IN ('ready', 'indexing', 'failed', 'removed')", name="ck_source_registrations_index_status"),
    )

    source_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    url: Mapped[str] = mapped_column(String(2048), unique=True, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    authorization_basis: Mapped[str] = mapped_column(String(128), nullable=False)
    index_status: Mapped[str] = mapped_column(String(16), nullable=False, default="ready", server_default="ready")
    index_generation: Mapped[str | None] = mapped_column(String(36))
    index_job_id: Mapped[str | None] = mapped_column(ForeignKey("ingestion_jobs.id", name="fk_source_registrations_index_job"))
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    registered_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
