"""Shopify product CSV snapshot rows for the Phase 6 proof of concept.

Revision ID: c83d7a16e902
Revises: b61c9e42d703
"""

from alembic import op
import sqlalchemy as sa

revision = "c83d7a16e902"
down_revision = "b61c9e42d703"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("source_file_name", sa.Text(), nullable=False),
        sa.Column("source_file_sha256", sa.String(64), nullable=False),
        sa.Column("source_row_number", sa.Integer(), nullable=False),
        sa.Column("source_exported_at", sa.DateTime(timezone=True)),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("snapshot_currency", sa.String(3)),
        sa.Column("visibility", sa.String(16), nullable=False, server_default="staff"),
        sa.Column("handle", sa.Text(), nullable=False),
        sa.Column("title", sa.Text()),
        sa.Column("body_html", sa.Text()),
        sa.Column("vendor", sa.Text()),
        sa.Column("product_category", sa.Text()),
        sa.Column("product_type", sa.Text()),
        sa.Column("tags", sa.Text()),
        sa.Column("published", sa.Boolean()),
        sa.Column("option1_name", sa.Text()),
        sa.Column("option1_value", sa.Text()),
        sa.Column("option1_linked_to", sa.Text()),
        sa.Column("option2_name", sa.Text()),
        sa.Column("option2_value", sa.Text()),
        sa.Column("option2_linked_to", sa.Text()),
        sa.Column("option3_name", sa.Text()),
        sa.Column("option3_value", sa.Text()),
        sa.Column("option3_linked_to", sa.Text()),
        sa.Column("variant_sku", sa.Text()),
        sa.Column("variant_grams", sa.Numeric()),
        sa.Column("variant_inventory_tracker", sa.Text()),
        sa.Column("variant_inventory_qty", sa.BigInteger()),
        sa.Column("variant_inventory_policy", sa.Text()),
        sa.Column("variant_fulfillment_service", sa.Text()),
        sa.Column("variant_price", sa.Numeric()),
        sa.Column("variant_compare_at_price", sa.Numeric()),
        sa.Column("variant_requires_shipping", sa.Boolean()),
        sa.Column("variant_taxable", sa.Boolean()),
        sa.Column("unit_price_total_measure", sa.Numeric()),
        sa.Column("unit_price_total_measure_unit", sa.Text()),
        sa.Column("unit_price_base_measure", sa.Numeric()),
        sa.Column("unit_price_base_measure_unit", sa.Text()),
        sa.Column("variant_barcodes", sa.Text()),
        sa.Column("image_src", sa.Text()),
        sa.Column("image_position", sa.Integer()),
        sa.Column("image_alt_text", sa.Text()),
        sa.Column("gift_card", sa.Boolean()),
        sa.Column("seo_title", sa.Text()),
        sa.Column("seo_description", sa.Text()),
        sa.Column("google_shopping_product_category", sa.Text()),
        sa.Column("google_shopping_gender", sa.Text()),
        sa.Column("google_shopping_age_group", sa.Text()),
        sa.Column("google_shopping_mpn", sa.Text()),
        sa.Column("google_shopping_condition", sa.Text()),
        sa.Column("google_shopping_custom_product", sa.Boolean()),
        sa.Column("google_shopping_custom_label_0", sa.Text()),
        sa.Column("google_shopping_custom_label_1", sa.Text()),
        sa.Column("google_shopping_custom_label_2", sa.Text()),
        sa.Column("google_shopping_custom_label_3", sa.Text()),
        sa.Column("google_shopping_custom_label_4", sa.Text()),
        sa.Column("meta_custom_category", sa.Text()),
        sa.Column("meta_custom_sub_brands", sa.Text()),
        sa.Column("meta_custom_sub_category", sa.Text()),
        sa.Column("meta_google_custom_product", sa.Text()),
        sa.Column("meta_shopify_bathtub_features", sa.Text()),
        sa.Column("meta_shopify_blade_material", sa.Text()),
        sa.Column("meta_shopify_color_pattern", sa.Text()),
        sa.Column("meta_shopify_connecting_thread", sa.Text()),
        sa.Column("meta_shopify_drain_location", sa.Text()),
        sa.Column("meta_shopify_flush_system", sa.Text()),
        sa.Column("meta_shopify_furniture_fixture_material", sa.Text()),
        sa.Column("meta_shopify_hardware_material", sa.Text()),
        sa.Column("meta_shopify_material", sa.Text()),
        sa.Column("meta_shopify_mounting_type", sa.Text()),
        sa.Column("meta_shopify_plumbing_trap_design", sa.Text()),
        sa.Column("meta_shopify_power_source", sa.Text()),
        sa.Column("meta_shopify_rug_mat_features", sa.Text()),
        sa.Column("meta_shopify_rug_mat_material", sa.Text()),
        sa.Column("meta_shopify_shape", sa.Text()),
        sa.Column("meta_shopify_shower_design", sa.Text()),
        sa.Column("meta_shopify_shower_features", sa.Text()),
        sa.Column("meta_shopify_shower_opening_type", sa.Text()),
        sa.Column("meta_shopify_sink_mounting_type", sa.Text()),
        sa.Column("meta_shopify_sink_type", sa.Text()),
        sa.Column("meta_shopify_size", sa.Text()),
        sa.Column("meta_shopify_toilet_shape", sa.Text()),
        sa.Column("meta_discovery_complementary_products", sa.Text()),
        sa.Column("meta_discovery_related_products", sa.Text()),
        sa.Column("meta_discovery_related_products_display", sa.Text()),
        sa.Column("meta_discovery_search_product_boosts", sa.Text()),
        sa.Column("variant_image", sa.Text()),
        sa.Column("variant_weight_unit", sa.Text()),
        sa.Column("variant_tax_code", sa.Text()),
        sa.Column("cost_per_item", sa.Numeric()),
        sa.Column("status", sa.Text()),
        sa.Column("variant_packed_length", sa.Numeric()),
        sa.Column("variant_packed_width", sa.Numeric()),
        sa.Column("variant_packed_height", sa.Numeric()),
        sa.Column("variant_packed_dimension_unit", sa.Text()),
        sa.UniqueConstraint("source_file_sha256", "source_row_number", name="uq_products_file_row"),
        sa.CheckConstraint("source_row_number >= 1", name="ck_products_source_row_number"),
        sa.CheckConstraint("length(source_file_sha256) = 64", name="ck_products_file_sha256"),
        sa.CheckConstraint("length(trim(handle)) > 0", name="ck_products_handle"),
        sa.CheckConstraint("visibility IN ('staff', 'admin')", name="ck_products_visibility"),
        sa.CheckConstraint("snapshot_currency IS NULL OR (length(snapshot_currency) = 3 AND snapshot_currency = upper(snapshot_currency))", name="ck_products_currency"),
    )
    op.create_index("ix_products_handle", "products", ["handle"])
    op.create_index("ix_products_variant_sku", "products", ["variant_sku"])


def downgrade() -> None:
    op.drop_index("ix_products_variant_sku", table_name="products")
    op.drop_index("ix_products_handle", table_name="products")
    op.drop_table("products")
