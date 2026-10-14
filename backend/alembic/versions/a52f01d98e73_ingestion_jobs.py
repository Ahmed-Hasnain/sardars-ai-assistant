"""Durable ingestion jobs and fail-closed index publication.

Revision ID: a52f01d98e73
Revises: f34a2d6c91b7
"""

from alembic import op
import sqlalchemy as sa

revision = "a52f01d98e73"
down_revision = "f34a2d6c91b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("request", sa.JSON(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("run_token", sa.String(36)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("result", sa.JSON()),
        sa.Column("error_code", sa.String(32)),
        sa.Column("error_message", sa.String(256)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("operation IN ('import', 'remove')", name="ck_ingestion_jobs_operation"),
        sa.CheckConstraint("status IN ('pending', 'processing', 'completed', 'failed')", name="ck_ingestion_jobs_status"),
        sa.CheckConstraint("attempts >= 0 AND attempts <= 3", name="ck_ingestion_jobs_attempts"),
    )
    op.add_column("source_registrations", sa.Column("index_status", sa.String(16), nullable=False, server_default="ready"))
    op.add_column("source_registrations", sa.Column("index_generation", sa.String(36)))
    op.add_column("source_registrations", sa.Column("index_job_id", sa.String(36)))
    for name in ("fetched_at", "last_indexed_at", "last_synced_at"):
        op.add_column("source_registrations", sa.Column(name, sa.DateTime(timezone=True)))
    op.create_foreign_key("fk_source_registrations_index_job", "source_registrations", "ingestion_jobs", ["index_job_id"], ["id"])
    op.create_check_constraint("ck_source_registrations_index_status", "source_registrations", "index_status IN ('ready', 'indexing', 'failed', 'removed')")


def downgrade() -> None:
    op.drop_constraint("ck_source_registrations_index_status", "source_registrations", type_="check")
    op.drop_constraint("fk_source_registrations_index_job", "source_registrations", type_="foreignkey")
    for name in ("last_synced_at", "last_indexed_at", "fetched_at", "index_job_id", "index_generation", "index_status"):
        op.drop_column("source_registrations", name)
    op.drop_table("ingestion_jobs")
