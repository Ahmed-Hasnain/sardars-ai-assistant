"""Authenticated source provenance and local stored originals.

Revision ID: b61c9e42d703
Revises: a52f01d98e73
"""
from alembic import op
import sqlalchemy as sa

revision = "b61c9e42d703"
down_revision = "a52f01d98e73"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ingestion_jobs", sa.Column("submitted_by_user_id", sa.Integer()))
    op.create_foreign_key("fk_ingestion_jobs_submitter", "ingestion_jobs", "users", ["submitted_by_user_id"], ["id"], ondelete="SET NULL")
    for name, length in (("title", 500), ("storage_key", 36), ("original_filename", 200), ("media_type", 80), ("file_sha256", 64)):
        op.add_column("source_registrations", sa.Column(name, sa.String(length)))


def downgrade() -> None:
    for name in ("file_sha256", "media_type", "original_filename", "storage_key", "title"):
        op.drop_column("source_registrations", name)
    op.drop_constraint("fk_ingestion_jobs_submitter", "ingestion_jobs", type_="foreignkey")
    op.drop_column("ingestion_jobs", "submitted_by_user_id")
