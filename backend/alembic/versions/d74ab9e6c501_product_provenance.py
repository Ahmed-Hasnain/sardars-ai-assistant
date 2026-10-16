"""Record original row role and edited-value provenance for product tools.

Revision ID: d74ab9e6c501
Revises: c83d7a16e902
"""

from alembic import op
import sqlalchemy as sa

revision = "d74ab9e6c501"
down_revision = "c83d7a16e902"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("products", sa.Column("source_row_kind", sa.String(16), nullable=False, server_default="unclassified"))
    op.add_column("products", sa.Column("price_origin", sa.String(24), nullable=False, server_default="unknown"))
    op.add_column("products", sa.Column("sku_origin", sa.String(24), nullable=False, server_default="unknown"))
    op.create_check_constraint("ck_products_row_kind", "products", "source_row_kind IN ('unclassified', 'variant', 'image_only')")
    op.create_check_constraint("ck_products_price_origin", "products", "price_origin IN ('unknown', 'synthetic_test', 'original_export')")
    op.create_check_constraint("ck_products_sku_origin", "products", "sku_origin IN ('unknown', 'synthetic_test', 'original_export')")


def downgrade() -> None:
    op.drop_constraint("ck_products_sku_origin", "products", type_="check")
    op.drop_constraint("ck_products_price_origin", "products", type_="check")
    op.drop_constraint("ck_products_row_kind", "products", type_="check")
    op.drop_column("products", "sku_origin")
    op.drop_column("products", "price_origin")
    op.drop_column("products", "source_row_kind")
