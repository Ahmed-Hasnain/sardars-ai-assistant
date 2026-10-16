"""Flat Shopify CSV snapshot rows, preserving variant/image continuation rows.

A local row ID is not a Shopify product/variant ID. Export times and currency
remain unknown until supplied. No imported field proves a changing fact current.
"""

from datetime import datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, Identity, Integer, Numeric,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Product(Base):
    """One CSV data record; handles and SKUs may repeat across rows/snapshots."""

    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("source_file_sha256", "source_row_number", name="uq_products_file_row"),
        CheckConstraint("source_row_number >= 1", name="ck_products_source_row_number"),
        CheckConstraint("length(source_file_sha256) = 64", name="ck_products_file_sha256"),
        CheckConstraint("length(trim(handle)) > 0", name="ck_products_handle"),
        CheckConstraint("visibility IN ('staff', 'admin')", name="ck_products_visibility"),
        CheckConstraint("snapshot_currency IS NULL OR (length(snapshot_currency) = 3 AND snapshot_currency = upper(snapshot_currency))", name="ck_products_currency"),
        CheckConstraint("source_row_kind IN ('unclassified', 'variant', 'image_only')", name="ck_products_row_kind"),
        CheckConstraint("price_origin IN ('unknown', 'synthetic_test', 'original_export')", name="ck_products_price_origin"),
        CheckConstraint("sku_origin IN ('unknown', 'synthetic_test', 'original_export')", name="ck_products_sku_origin"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), Identity(), primary_key=True)
    source_file_name: Mapped[str] = mapped_column(Text)
    source_file_sha256: Mapped[str] = mapped_column(String(64))
    source_row_number: Mapped[int] = mapped_column(Integer)
    source_exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    snapshot_currency: Mapped[str | None] = mapped_column(String(3))
    visibility: Mapped[str] = mapped_column(String(16), default="staff", server_default="staff")
    source_row_kind: Mapped[str] = mapped_column(String(16), default="unclassified", server_default="unclassified")
    price_origin: Mapped[str] = mapped_column(String(24), default="unknown", server_default="unknown")
    sku_origin: Mapped[str] = mapped_column(String(24), default="unknown", server_default="unknown")

    handle: Mapped[str] = mapped_column(Text, index=True, info={"csv_header": 'Handle'})
    title: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Title'})
    body_html: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Body (HTML)'})
    vendor: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Vendor'})
    product_category: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Product Category'})
    product_type: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Type'})
    tags: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Tags'})
    published: Mapped[bool | None] = mapped_column(Boolean, info={"csv_header": 'Published'})
    option1_name: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Option1 Name'})
    option1_value: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Option1 Value'})
    option1_linked_to: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Option1 Linked To'})
    option2_name: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Option2 Name'})
    option2_value: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Option2 Value'})
    option2_linked_to: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Option2 Linked To'})
    option3_name: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Option3 Name'})
    option3_value: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Option3 Value'})
    option3_linked_to: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Option3 Linked To'})
    variant_sku: Mapped[str | None] = mapped_column(Text, index=True, info={"csv_header": 'Variant SKU'})
    variant_grams: Mapped[Decimal | None] = mapped_column(Numeric, info={"csv_header": 'Variant Grams'})
    variant_inventory_tracker: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Variant Inventory Tracker'})
    variant_inventory_qty: Mapped[int | None] = mapped_column(BigInteger, info={"csv_header": 'Variant Inventory Qty'})
    variant_inventory_policy: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Variant Inventory Policy'})
    variant_fulfillment_service: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Variant Fulfillment Service'})
    variant_price: Mapped[Decimal | None] = mapped_column(Numeric, info={"csv_header": 'Variant Price'})
    variant_compare_at_price: Mapped[Decimal | None] = mapped_column(Numeric, info={"csv_header": 'Variant Compare At Price'})
    variant_requires_shipping: Mapped[bool | None] = mapped_column(Boolean, info={"csv_header": 'Variant Requires Shipping'})
    variant_taxable: Mapped[bool | None] = mapped_column(Boolean, info={"csv_header": 'Variant Taxable'})
    unit_price_total_measure: Mapped[Decimal | None] = mapped_column(Numeric, info={"csv_header": 'Unit Price Total Measure'})
    unit_price_total_measure_unit: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Unit Price Total Measure Unit'})
    unit_price_base_measure: Mapped[Decimal | None] = mapped_column(Numeric, info={"csv_header": 'Unit Price Base Measure'})
    unit_price_base_measure_unit: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Unit Price Base Measure Unit'})
    variant_barcodes: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Variant Barcodes'})
    image_src: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Image Src'})
    image_position: Mapped[int | None] = mapped_column(Integer, info={"csv_header": 'Image Position'})
    image_alt_text: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Image Alt Text'})
    gift_card: Mapped[bool | None] = mapped_column(Boolean, info={"csv_header": 'Gift Card'})
    seo_title: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'SEO Title'})
    seo_description: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'SEO Description'})
    google_shopping_product_category: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Google Shopping / Google Product Category'})
    google_shopping_gender: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Google Shopping / Gender'})
    google_shopping_age_group: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Google Shopping / Age Group'})
    google_shopping_mpn: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Google Shopping / MPN'})
    google_shopping_condition: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Google Shopping / Condition'})
    google_shopping_custom_product: Mapped[bool | None] = mapped_column(Boolean, info={"csv_header": 'Google Shopping / Custom Product'})
    google_shopping_custom_label_0: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Google Shopping / Custom Label 0'})
    google_shopping_custom_label_1: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Google Shopping / Custom Label 1'})
    google_shopping_custom_label_2: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Google Shopping / Custom Label 2'})
    google_shopping_custom_label_3: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Google Shopping / Custom Label 3'})
    google_shopping_custom_label_4: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Google Shopping / Custom Label 4'})
    meta_custom_category: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Category (product.metafields.custom.category)'})
    meta_custom_sub_brands: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Sub Brands (product.metafields.custom.sub_brands)'})
    meta_custom_sub_category: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Sub Category (product.metafields.custom.sub_category)'})
    meta_google_custom_product: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Google: Custom Product (product.metafields.mm-google-shopping.custom_product)'})
    meta_shopify_bathtub_features: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Bathtub features (product.metafields.shopify.bathtub-features)'})
    meta_shopify_blade_material: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Blade material (product.metafields.shopify.blade-material)'})
    meta_shopify_color_pattern: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Color (product.metafields.shopify.color-pattern)'})
    meta_shopify_connecting_thread: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Connecting thread (product.metafields.shopify.connecting-thread)'})
    meta_shopify_drain_location: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Drain location (product.metafields.shopify.drain-location)'})
    meta_shopify_flush_system: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Flush system (product.metafields.shopify.flush-system)'})
    meta_shopify_furniture_fixture_material: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Furniture/Fixture material (product.metafields.shopify.furniture-fixture-material)'})
    meta_shopify_hardware_material: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Hardware material (product.metafields.shopify.hardware-material)'})
    meta_shopify_material: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Material (product.metafields.shopify.material)'})
    meta_shopify_mounting_type: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Mounting type (product.metafields.shopify.mounting-type)'})
    meta_shopify_plumbing_trap_design: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Plumbing trap design (product.metafields.shopify.plumbing-trap-design)'})
    meta_shopify_power_source: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Power source (product.metafields.shopify.power-source)'})
    meta_shopify_rug_mat_features: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Rug/Mat features (product.metafields.shopify.rug-mat-features)'})
    meta_shopify_rug_mat_material: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Rug/Mat material (product.metafields.shopify.rug-mat-material)'})
    meta_shopify_shape: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Shape (product.metafields.shopify.shape)'})
    meta_shopify_shower_design: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Shower design (product.metafields.shopify.shower-design)'})
    meta_shopify_shower_features: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Shower features (product.metafields.shopify.shower-features)'})
    meta_shopify_shower_opening_type: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Shower opening type (product.metafields.shopify.shower-opening-type)'})
    meta_shopify_sink_mounting_type: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Sink mounting type (product.metafields.shopify.sink-mounting-type)'})
    meta_shopify_sink_type: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Sink type (product.metafields.shopify.sink-type)'})
    meta_shopify_size: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Size (product.metafields.shopify.size)'})
    meta_shopify_toilet_shape: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Toilet shape (product.metafields.shopify.toilet-shape)'})
    meta_discovery_complementary_products: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Complementary products (product.metafields.shopify--discovery--product_recommendation.complementary_products)'})
    meta_discovery_related_products: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Related products (product.metafields.shopify--discovery--product_recommendation.related_products)'})
    meta_discovery_related_products_display: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Related products settings (product.metafields.shopify--discovery--product_recommendation.related_products_display)'})
    meta_discovery_search_product_boosts: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Search product boosts (product.metafields.shopify--discovery--product_search_boost.queries)'})
    variant_image: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Variant Image'})
    variant_weight_unit: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Variant Weight Unit'})
    variant_tax_code: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Variant Tax Code'})
    cost_per_item: Mapped[Decimal | None] = mapped_column(Numeric, info={"csv_header": 'Cost per item'})
    status: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Status'})
    variant_packed_length: Mapped[Decimal | None] = mapped_column(Numeric, info={"csv_header": 'Variant Packed Length'})
    variant_packed_width: Mapped[Decimal | None] = mapped_column(Numeric, info={"csv_header": 'Variant Packed Width'})
    variant_packed_height: Mapped[Decimal | None] = mapped_column(Numeric, info={"csv_header": 'Variant Packed Height'})
    variant_packed_dimension_unit: Mapped[str | None] = mapped_column(Text, info={"csv_header": 'Variant Packed Dimension Unit'})


# Exact supplied header spelling is retained even where SQL names are shortened.
# Unnamed trailing spreadsheet columns are not product fields.
SHOPIFY_COLUMN_MAP: Mapping[str, str] = MappingProxyType({
    column.info["csv_header"]: column.name
    for column in Product.__table__.columns if "csv_header" in column.info
})
