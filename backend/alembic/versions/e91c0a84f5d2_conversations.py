"""Persist owned, expiring staff conversations.

Revision ID: e91c0a84f5d2
Revises: d74ab9e6c501
"""

from alembic import op
import sqlalchemy as sa


revision = "e91c0a84f5d2"
down_revision = "d74ab9e6c501"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("required_role", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("required_role IN ('admin', 'staff')", name="ck_conversations_required_role"),
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])
    op.create_index("ix_conversations_updated_at", "conversations", ["updated_at"])
    op.create_index("ix_conversations_expires_at", "conversations", ["expires_at"])
    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer, "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("route", sa.String(24)),
        sa.Column("model", sa.String(128)),
        sa.Column("prompt_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("duration_ms", sa.Float()),
        sa.Column("source_ids", sa.JSON(), nullable=False),
        sa.Column("product_handles", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_conversation_messages_role"),
    )
    op.create_index("ix_conversation_messages_conversation_id", "conversation_messages", ["conversation_id"])


def downgrade() -> None:
    op.drop_index("ix_conversation_messages_conversation_id", table_name="conversation_messages")
    op.drop_table("conversation_messages")
    op.drop_index("ix_conversations_expires_at", table_name="conversations")
    op.drop_index("ix_conversations_updated_at", table_name="conversations")
    op.drop_index("ix_conversations_user_id", table_name="conversations")
    op.drop_table("conversations")
