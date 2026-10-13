"""source registrations and role visibility

Revision ID: f34a2d6c91b7
Revises: 6a9d2c7e41b0
"""

from alembic import op
import sqlalchemy as sa


revision = "f34a2d6c91b7"
down_revision = "6a9d2c7e41b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_registrations",
        sa.Column("source_id", sa.String(length=64), primary_key=True),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("visibility", sa.String(length=16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("authorization_basis", sa.String(length=128), nullable=False),
        sa.Column("registered_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("visibility IN ('public', 'staff', 'admin')", name="ck_source_registrations_visibility"),
        sa.UniqueConstraint("url"),
    )


def downgrade() -> None:
    op.drop_table("source_registrations")
