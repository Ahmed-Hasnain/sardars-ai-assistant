"""Classify retained Shopify rows after the owner's manual test-value edits.

Run only for the documented synthetic product proof of concept. This command
never changes a SKU or price. It marks their provenance after verifying the
retained CSV and every stored row in one transaction.
"""

import argparse
import json
from pathlib import Path

from sqlalchemy import bindparam, select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.products import Product
from app.ingestion.shopify_products import ProductImportError, prepare


def mark_snapshot(db: Session, original_path: Path, expected_sha256: str) -> dict[str, int | str]:
    prepared = prepare(original_path)
    if prepared.file_sha256 != expected_sha256:
        raise ProductImportError("Retained CSV checksum differs from the expected snapshot")
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SET LOCAL statement_timeout = '15s'"))
        db.execute(text("SET LOCAL lock_timeout = '2s'"))
        db.execute(text("LOCK TABLE products IN SHARE ROW EXCLUSIVE MODE"))
    stored = db.execute(select(
        Product.id, Product.source_file_sha256, Product.source_row_number,
        Product.handle, Product.variant_sku, Product.variant_price,
        Product.source_row_kind, Product.price_origin, Product.sku_origin,
    ).order_by(Product.source_row_number)).all()
    if len(stored) != len(prepared.rows):
        raise ProductImportError("Stored row count differs from retained CSV")
    variants = images = synthetic_skus = original_skus = 0
    changes = []
    for actual, expected in zip(stored, prepared.rows, strict=True):
        if (actual.source_file_sha256 != expected_sha256
                or actual.source_row_number != expected["source_row_number"]
                or actual.handle != expected["handle"]):
            raise ProductImportError("Stored row identity differs from retained CSV")
        if not actual.variant_sku or actual.variant_price is None:
            raise ProductImportError("A stored row lacks the reported test SKU or price")
        if expected["variant_price"] is not None:
            kind = "variant"
            variants += 1
        elif (expected["image_src"] is not None
              and expected["variant_sku"] is None
              and all(expected[f"option{n}_value"] is None for n in (1, 2, 3))):
            kind = "image_only"
            images += 1
        else:
            raise ProductImportError("Original CSV contains an unclassified row")
        sku_origin = "original_export" if expected["variant_sku"] == actual.variant_sku else "synthetic_test"
        if sku_origin == "original_export":
            original_skus += 1
        else:
            synthetic_skus += 1
        target = (kind, "synthetic_test", sku_origin)
        current = (actual.source_row_kind, actual.price_origin, actual.sku_origin)
        if current != ("unclassified", "unknown", "unknown") and current != target:
            raise ProductImportError("Stored provenance differs; no flags overwritten")
        if current != target:
            changes.append({"_row_id": actual.id, "source_row_kind": kind,
                            "price_origin": "synthetic_test", "sku_origin": sku_origin})
    if changes:
        db.execute(update(Product.__table__).where(Product.id == bindparam("_row_id")), changes)
    return {"status": "marked" if changes else "verified_unchanged", "rows": len(stored),
            "variants": variants, "image_only": images, "synthetic_prices": len(stored),
            "synthetic_skus": synthetic_skus, "original_export_skus": original_skus,
            "updated_flags": len(changes), "source_file_sha256": expected_sha256}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path)
    parser.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()
    try:
        from app.db.session import SessionLocal
        with SessionLocal.begin() as db:
            result = mark_snapshot(db, args.original, args.expected_sha256)
        print(json.dumps(result, indent=2))
    except (ProductImportError, OSError, SQLAlchemyError):
        parser.exit(1, "Product test-data classification refused; database unchanged\n")


if __name__ == "__main__":
    main()
