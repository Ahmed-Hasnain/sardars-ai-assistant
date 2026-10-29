"""Shopify row shape, exact identifiers and snapshot provenance."""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models import Product
from app.db.products import SHOPIFY_COLUMN_MAP


@pytest.fixture
def sessions():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine)
    engine.dispose()


def row(number=1, **changes):
    values = dict(
        source_file_name="products_export.csv", source_file_sha256="a" * 64,
        source_row_number=number, handle="test-basin",
    )
    return Product(**(values | changes))


def test_variant_and_image_rows_can_share_handle_and_sku(sessions):
    with sessions.begin() as db:
        db.add_all([
            row(title="Test basin", variant_sku="000123", option1_value="White"),
            row(2, variant_sku="000123", option1_value="Black"),
            row(3, image_src="https://example.invalid/basin.jpg", image_position=2),
        ])
    with sessions() as db:
        products = list(db.scalars(select(Product).order_by(Product.source_row_number)))
        assert len(products) == 3 and len({p.id for p in products}) == 3
        assert all(p.handle == "test-basin" for p in products)
        assert products[1].title is None and products[2].variant_price is None
        assert products[2].variant_sku is None


def test_money_identifiers_html_and_metafields_survive_round_trip(sessions):
    values = {
        "Variant Price": Decimal("10999.95"), "Cost per item": Decimal("0.10"),
        "Variant Inventory Qty": -3, "Variant SKU": "000123",
        "Variant Barcodes": "gtin:00012345678905; INTERNAL-123",
        "Body (HTML)": "<p>Test basin, white &amp; black</p>",
        "Related products settings (product.metafields.shopify--discovery--product_recommendation.related_products_display)": "only related",
        "Furniture/Fixture material (product.metafields.shopify.furniture-fixture-material)": "ceramic",
        "Google Shopping / MPN": "001234",
        "Variant Taxable": False,
    }
    with sessions.begin() as db:
        db.add(row(**{SHOPIFY_COLUMN_MAP[header]: value for header, value in values.items()}))
    with sessions() as db:
        saved = db.scalar(select(Product))
        for header, value in values.items():
            assert getattr(saved, SHOPIFY_COLUMN_MAP[header]) == value


def test_unknown_price_stock_currency_and_export_time_remain_unknown(sessions):
    with sessions.begin() as db:
        db.add(row())
    with sessions() as db:
        saved = db.scalar(select(Product))
        assert saved.variant_price is saved.variant_inventory_qty is None
        assert saved.published is saved.variant_taxable is None
        assert saved.source_exported_at is saved.snapshot_currency is None
        assert saved.imported_at is not None and saved.visibility == "staff"


def test_duplicate_file_record_is_rejected_but_new_snapshot_is_distinct(sessions):
    with sessions.begin() as db:
        db.add(row())
    with pytest.raises(IntegrityError), sessions.begin() as db:
        db.add(row())
    with sessions.begin() as db:
        db.add(row(source_file_sha256="b" * 64))
    with sessions() as db:
        assert len(list(db.scalars(select(Product)))) == 2


@pytest.mark.parametrize("changes", [
    {"source_row_number": 0}, {"source_row_number": -1},
    {"source_file_sha256": "short"}, {"source_file_sha256": None},
    {"source_file_name": None}, {"handle": None}, {"handle": "  "},
    {"visibility": "public"}, {"snapshot_currency": "pkr"}, {"snapshot_currency": "PK"},
])
def test_invalid_provenance_identity_and_visibility_are_rejected(sessions, changes):
    with pytest.raises(IntegrityError), sessions.begin() as db:
        db.add(row(**changes))


def test_explicit_snapshot_currency_and_admin_visibility_are_preserved(sessions):
    with sessions.begin() as db:
        db.add(row(snapshot_currency="PKR", visibility="admin"))
    with sessions() as db:
        saved = db.scalar(select(Product))
        assert saved.snapshot_currency == "PKR" and saved.visibility == "admin"
