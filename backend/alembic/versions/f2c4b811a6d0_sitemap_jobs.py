"""Link sitemap page jobs to a bounded discovery job.

Revision ID: f2c4b811a6d0
Revises: e91c0a84f5d2
"""
from alembic import op
import sqlalchemy as sa

revision = "f2c4b811a6d0"
down_revision = "e91c0a84f5d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_ingestion_jobs_operation", "ingestion_jobs", type_="check")
    op.create_check_constraint("ck_ingestion_jobs_operation", "ingestion_jobs", "operation IN ('import', 'remove', 'crawl')")
    op.add_column("ingestion_jobs", sa.Column("parent_job_id", sa.String(36)))
    op.create_index("ix_ingestion_jobs_parent_job_id", "ingestion_jobs", ["parent_job_id"])


def downgrade() -> None:
    op.drop_index("ix_ingestion_jobs_parent_job_id", table_name="ingestion_jobs")
    op.drop_column("ingestion_jobs", "parent_job_id")
    op.drop_constraint("ck_ingestion_jobs_operation", "ingestion_jobs", type_="check")
    op.create_check_constraint("ck_ingestion_jobs_operation", "ingestion_jobs", "operation IN ('import', 'remove')")
