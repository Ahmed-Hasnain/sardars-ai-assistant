"""Actual CSV parsing, safe exact mapping and transactional snapshot behavior."""

import csv
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import sys

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.products import Product, SHOPIFY_COLUMN_MAP
from app.ingestion import shopify_products as importer


@pytest.fixture
def sessions():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine)
    engine.dispose()


def csv_file(tmp_path, rows=None, headers=None):
    path = tmp_path / "products.csv"
    headers = list(SHOPIFY_COLUMN_MAP) if headers is None else headers
    rows = [{"Handle": "test-basin", "Title": "Test basin"}] if rows is None else rows
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        for row in rows:
            writer.writerow([row.get(header, "") for header in headers])
    return path


def test_mapping_handles_reordered_headers_multiline_html_and_exact_values(tmp_path):
    html = '<p>First, second &amp; third</p>\n<p title="quoted">More</p>'
    path = csv_file(tmp_path, [{
        "Handle": "test-basin", "Body (HTML)": html, "Variant SKU": "000123",
        "Variant Barcodes": "gtin:00012345678905", "Variant Price": "19.90",
        "Published": "TRUE", "Variant Taxable": "false", "Variant Inventory Qty": "-3",
    }], list(reversed(SHOPIFY_COLUMN_MAP)))
    prepared = importer.prepare(path)
    row = prepared.rows[0]
    assert row["handle"] == "test-basin" and row["body_html"] == html
    assert row["variant_sku"] == "000123" and row["variant_barcodes"] == "gtin:00012345678905"
    assert row["variant_price"] == Decimal("19.90") and isinstance(row["variant_price"], Decimal)
    assert row["published"] is True and row["variant_taxable"] is False
    assert row["variant_inventory_qty"] == -3
    assert row["source_row_number"] == 1
    assert prepared.file_sha256 == row["source_file_sha256"] == sha256(path.read_bytes()).hexdigest()
    assert row["source_exported_at"] is row["snapshot_currency"] is None


@pytest.mark.parametrize("mode", ["missing", "extra", "duplicate", "unnamed"])
def test_bad_headers_are_refused_before_any_import(tmp_path, mode):
    headers = list(SHOPIFY_COLUMN_MAP)
    if mode == "missing": headers.pop()
    if mode == "extra": headers.append("unexpected")
    if mode == "duplicate": headers[-1] = headers[0]
    if mode == "unnamed": headers[-1] = ""
    with pytest.raises(importer.ProductImportError, match="headers"):
        importer.prepare(csv_file(tmp_path, headers=headers))


@pytest.mark.parametrize("header,value", [
    ("Handle", ""), ("Handle", "  "), ("Title", "private\x00text"),
    ("Published", "yes"), ("Variant Inventory Qty", "1.5"),
    ("Variant Inventory Qty", str(2**63)), ("Image Position", str(2**31)),
    ("Variant Price", "secret_bad_price"), ("Variant Price", "NaN"),
    ("Variant Price", "Infinity"), ("Variant Price", "1e999999"),
])
def test_bad_cells_are_rejected_without_echoing_values(tmp_path, header, value):
    path = csv_file(tmp_path, [{"Handle": "test-basin", header: value}])
    with pytest.raises(importer.ProductImportError, match="Record 1") as error:
        importer.prepare(path)
    assert "secret_bad_price" not in str(error.value)
    assert "private" not in str(error.value)


def test_empty_header_only_bad_width_and_bad_quote_are_rejected(tmp_path):
    path = csv_file(tmp_path, rows=[])
    with pytest.raises(importer.ProductImportError, match="at least one"):
        importer.prepare(path)
    with path.open("a") as stream:
        stream.write('"unterminated')
    with pytest.raises(importer.ProductImportError, match="quoting"):
        importer.prepare(path)
    path = csv_file(tmp_path)
    with path.open("a") as stream:
        stream.write("only-one-column\n")
    with pytest.raises(importer.ProductImportError, match="Record 2"):
        importer.prepare(path)


def test_file_record_and_field_limits_restore_csv_configuration(tmp_path, monkeypatch):
    path = csv_file(tmp_path, [{"Handle": "a"}, {"Handle": "b"}])
    monkeypatch.setattr(importer, "MAX_RECORDS", 1)
    old_limit = csv.field_size_limit()
    with pytest.raises(importer.ProductImportError, match="record limit"):
        importer.prepare(path)
    assert csv.field_size_limit() == old_limit
    monkeypatch.setattr(importer, "MAX_FILE_BYTES", 10)
    with pytest.raises(importer.ProductImportError, match="file limit"):
        importer.prepare(path)


def test_oversized_field_and_wrong_encoding_are_rejected(tmp_path, monkeypatch):
    path = csv_file(tmp_path, [{"Handle": "test", "Body (HTML)": "x" * 1000}])
    monkeypatch.setattr(importer, "MAX_FIELD_CHARACTERS", 200)
    with pytest.raises(importer.ProductImportError, match="field size"):
        importer.prepare(path)
    path.write_bytes(b"\xff\xfe")
    with pytest.raises(importer.ProductImportError, match="UTF-8"):
        importer.prepare(path)


def test_original_data_and_image_rows_import_once_and_replay_without_writes(tmp_path, sessions):
    path = csv_file(tmp_path, [
        {"Handle": "test-basin", "Title": "Test basin", "Variant Price": "19.90"},
        {"Handle": "test-basin", "Image Src": "https://example.invalid/test.jpg"},
    ])
    prepared = importer.prepare(path)
    result = importer.apply(sessions, prepared)
    assert result["inserted_rows"] == 2 and result["verified_rows"] == 2
    with sessions() as db:
        original = [(row.id, row.imported_at) for row in db.scalars(select(Product).order_by(Product.id))]
    replay = importer.apply(sessions, prepared)
    assert replay["status"] == "verified_unchanged" and replay["inserted_rows"] == 0
    assert replay["skipped_rows"] == 2
    with sessions() as db:
        saved = list(db.scalars(select(Product).order_by(Product.id)))
        assert [(row.id, row.imported_at) for row in saved] == original
        assert saved[1].variant_price is saved[1].variant_inventory_qty is saved[1].title is None


def test_existing_manual_edits_are_preserved_and_repeat_is_refused(tmp_path, sessions):
    prepared = importer.prepare(csv_file(tmp_path))
    importer.apply(sessions, prepared)
    with sessions.begin() as db:
        db.scalar(select(Product)).variant_sku = "TEST-ONLY-SKU"
    with pytest.raises(importer.ProductImportError, match="no data overwritten"):
        importer.apply(sessions, prepared)
    with sessions() as db:
        assert db.scalar(select(Product.variant_sku)) == "TEST-ONLY-SKU"


def test_another_snapshot_is_refused_without_deleting_or_replacing_rows(tmp_path, sessions):
    path = csv_file(tmp_path)
    first = importer.prepare(path)
    importer.apply(sessions, first)
    csv_file(tmp_path, [{"Handle": "different-basin"}])
    with pytest.raises(importer.ProductImportError, match="another snapshot"):
        importer.apply(sessions, importer.prepare(path))
    with sessions() as db:
        assert db.scalar(select(Product.handle)) == "test-basin"


def test_partial_existing_snapshot_is_not_silently_completed(tmp_path, sessions):
    prepared = importer.prepare(csv_file(tmp_path, [{"Handle": "a"}, {"Handle": "b"}]))
    with sessions.begin() as db:
        db.add(Product(**prepared.rows[0]))
    with pytest.raises(importer.ProductImportError, match="incomplete"):
        importer.apply(sessions, prepared)
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(Product)) == 1


def test_late_database_failure_rolls_back_earlier_batches(tmp_path, sessions, monkeypatch):
    prepared = importer.prepare(csv_file(tmp_path, [{"Handle": "a"}, {"Handle": "b"}]))
    monkeypatch.setattr(importer, "INSERT_BATCH_SIZE", 1)
    engine = sessions.kw["bind"]
    inserts = 0

    def fail_second(connection, cursor, statement, parameters, context, executemany):
        nonlocal inserts
        if statement.startswith("INSERT INTO products"):
            inserts += 1
            if inserts == 2:
                raise SQLAlchemyError("simulated database failure")

    event.listen(engine, "before_cursor_execute", fail_second)
    try:
        with pytest.raises(SQLAlchemyError):
            importer.apply(sessions, prepared)
    finally:
        event.remove(engine, "before_cursor_execute", fail_second)
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(Product)) == 0


def test_supplied_export_time_currency_and_visibility_survive_replay(tmp_path, sessions):
    options = importer.ImportOptions(exported_at=datetime(2026, 10, 15, tzinfo=timezone.utc),
                                     currency="PKR", visibility="admin")
    prepared = importer.prepare(csv_file(tmp_path), options)
    importer.apply(sessions, prepared)
    assert importer.apply(sessions, prepared)["status"] == "verified_unchanged"
    with sessions() as db:
        row = db.scalar(select(Product))
        assert row.snapshot_currency == "PKR" and row.visibility == "admin"


def test_export_options_require_explicit_aware_time_and_uppercase_currency():
    with pytest.raises(ValidationError):
        importer.ImportOptions(exported_at=datetime(2026, 10, 15))
    with pytest.raises(ValidationError):
        importer.ImportOptions(currency="pkr")


def test_retained_original_is_exact_private_and_not_silently_overwritten(tmp_path):
    prepared = importer.prepare(csv_file(tmp_path))
    target = importer.preserve_original(prepared, tmp_path / "originals")
    assert target.read_bytes() == prepared.original and target.stat().st_mode & 0o777 == 0o600
    assert importer.preserve_original(prepared, target.parent) == target
    target.write_bytes(b"corrupt")
    with pytest.raises(importer.ProductImportError, match="checksum"):
        importer.preserve_original(prepared, target.parent)


def test_cli_preview_is_offline_and_apply_requires_expected_checksum(tmp_path, monkeypatch, capsys):
    path = csv_file(tmp_path)
    monkeypatch.setattr(sys, "argv", ["shopify_products", str(path)])
    importer.main()
    assert '"database_changed": false' in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["shopify_products", str(path), "--apply", "--expected-sha256", "wrong"])
    with pytest.raises(SystemExit) as result:
        importer.main()
    assert result.value.code == 1 and "matching the previewed file" in capsys.readouterr().err
