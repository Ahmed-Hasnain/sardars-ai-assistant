"""internal users and revocable sessions

Revision ID: 6a9d2c7e41b0
Revises: 87b27fb5a926
"""

from alembic import op
import sqlalchemy as sa


revision = "6a9d2c7e41b0"
down_revision = "87b27fb5a926"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("role IN ('admin', 'staff')", name="ck_users_role"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "login_sessions",
        sa.Column("token_hash", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at_epoch", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_login_sessions_user_id", "login_sessions", ["user_id"])
    op.create_index("ix_login_sessions_expires_at_epoch", "login_sessions", ["expires_at_epoch"])


def downgrade() -> None:
    op.drop_index("ix_login_sessions_expires_at_epoch", table_name="login_sessions")
    op.drop_index("ix_login_sessions_user_id", table_name="login_sessions")
    op.drop_table("login_sessions")
    op.drop_table("users")
