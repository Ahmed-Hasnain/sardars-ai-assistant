"""Persist bounded external citation snapshots separately from company source IDs."""

from alembic import op
import sqlalchemy as sa

revision = "ae71c40b2359"
down_revision = "f2c4b811a6d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversation_messages", sa.Column(
        "web_sources", sa.JSON(), nullable=False, server_default=sa.text("'[]'"),
    ))


def downgrade() -> None:
    op.drop_column("conversation_messages", "web_sources")
