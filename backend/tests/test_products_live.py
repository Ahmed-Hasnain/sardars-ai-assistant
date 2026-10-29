"""Opt-in PostgreSQL migration/precision check, using a disposable schema only.

SARDARS_RUN_PRODUCTS_LIVE=1 PYTHONPATH=backend backend/.venv/bin/python -m pytest -q -s backend/tests/test_products_live.py
"""

from decimal import Decimal
import csv
import os
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import sessionmaker

from app.db.models import Product
from app.db.products import SHOPIFY_COLUMN_MAP


@pytest.mark.skipif(os.environ.get("SARDARS_RUN_PRODUCTS_LIVE") != "1", reason="opt-in local PostgreSQL integration")
def test_postgresql_upgrade_exact_values_and_downgrade(tmp_path):
    from app.db.session import engine

    assert engine.url.host in {"localhost", "127.0.0.1", "::1"}
    namespace = "sardars_products_test_" + uuid4().hex
    isolated = None
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{namespace}"')
    try:
        isolated = create_engine(engine.url, connect_args={
            "connect_timeout": 5, "options": f"-c search_path={namespace}",
        })
        config = Config("alembic.ini")
        with isolated.begin() as connection:
            config.attributes.update(connection=connection)
            command.upgrade(config, "b61c9e42d703")
            before = inspect(connection).get_table_names()
            command.upgrade(config, "head")
            actual = {column["name"] for column in inspect(connection).get_columns("products")}
            assert set(SHOPIFY_COLUMN_MAP.values()) <= actual
            assert len(actual) == 96
            command.check(config)
        sessions = sessionmaker(bind=isolated)
        precise = Decimal("12345678901234567890.12345678901234567890")
        with sessions.begin() as db:
            db.add_all([
                Product(handle="test-basin", variant_sku="000123", variant_barcodes="0000123456789",
                        variant_price=precise, source_file_name="test.csv", source_file_sha256="a" * 64,
                        source_row_number=1),
                Product(handle="test-basin", source_file_name="test.csv", source_file_sha256="a" * 64,
                        source_row_number=2, image_src="https://example.invalid/test.jpg"),
            ])
        with sessions() as db:
            saved = db.scalar(select(Product).where(Product.source_row_number == 1))
            assert saved.variant_price == precise and saved.variant_sku == "000123"
            assert saved.variant_barcodes == "0000123456789"
            assert saved.imported_at.tzinfo is not None and saved.source_exported_at is None
            assert db.scalar(text("SELECT count(*) FROM products")) == 2
        with isolated.begin() as connection:
            config.attributes.update(connection=connection)
            command.downgrade(config, "b61c9e42d703")
            assert set(inspect(connection).get_table_names()) == set(before)
            command.upgrade(config, "head")
            assert connection.exec_driver_sql("SELECT count(*) FROM products").scalar_one() == 0
            command.check(config)
        print("Isolated PostgreSQL upgrade/downgrade, exact decimal/identifier and metadata checks passed")
        # Exercise the actual CSV importer on an isolated PostgreSQL table,
        # including high precision and image-only continuation records.
        from app.ingestion.shopify_products import apply, prepare, verify_rows

        path = tmp_path / "products.csv"
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(SHOPIFY_COLUMN_MAP))
            writer.writeheader()
            writer.writerow({"Handle": "test-basin", "Title": "Test basin", "Variant Price": str(precise),
                             "Variant SKU": "000123", "Body (HTML)": '<p title="test">First, second</p>\n<p>Third</p>'})
            writer.writerow({"Handle": "test-basin", "Image Src": "https://example.invalid/test.jpg"})
        prepared = prepare(path)
        assert apply(sessions, prepared)["inserted_rows"] == 2
        replay = apply(sessions, prepared)
        assert replay["inserted_rows"] == 0 and replay["skipped_rows"] == 2
        with sessions() as db:
            verify_rows(db, prepared)
            assert db.scalar(select(Product.variant_price).where(Product.source_row_number == 1)) == precise
        print("Isolated PostgreSQL CSV import and exact no-write repeat verification passed")
    finally:
        if isolated is not None:
            isolated.dispose()
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{namespace}" CASCADE')
