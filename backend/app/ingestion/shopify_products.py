"""Bounded Shopify snapshot import with exact header mapping and atomic writes.

Preview is offline. --apply requires the checksum printed by the preview.
The first proof of concept accepts one immutable file snapshot, not a live sync.
"""

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import io
import json
from pathlib import Path
import re

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import BigInteger, Boolean, Integer, Numeric, func, insert, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from typing import Literal

from app.db.products import Product, SHOPIFY_COLUMN_MAP

MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_RECORDS = 10_000
MAX_FIELD_CHARACTERS = 250_000
INSERT_BATCH_SIZE = 250
INTEGER_TEXT = re.compile(r"^[+-]?[0-9]+$")


class ImportOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exported_at: AwareDatetime | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    visibility: Literal["staff", "admin"] = "staff"


class ProductImportError(ValueError):
    """Safe operator-facing error without source values or database details."""


@dataclass(frozen=True)
class PreparedImport:
    file_name: str
    file_sha256: str
    original: bytes
    rows: tuple[dict[str, object], ...]
    options: ImportOptions

    def summary(self) -> dict[str, object]:
        return {
            "file_name": self.file_name, "file_sha256": self.file_sha256,
            "file_bytes": len(self.original), "csv_columns": len(SHOPIFY_COLUMN_MAP),
            "records": len(self.rows), "distinct_handles": len({r["handle"] for r in self.rows}),
            "price_bearing_records": sum(r["variant_price"] is not None for r in self.rows),
            "nonempty_sku_records": sum(r["variant_sku"] is not None for r in self.rows),
            "exported_at": self.options.exported_at.isoformat() if self.options.exported_at else None,
            "currency": self.options.currency, "visibility": self.options.visibility,
            "company_facts_current": False,
        }


def _cell(value: str, header: str, record: int) -> object:
    column = Product.__table__.columns[SHOPIFY_COLUMN_MAP[header]]
    if "\x00" in value:
        raise ProductImportError(f"Record {record}: NUL character in {header}")
    if len(value) > MAX_FIELD_CHARACTERS:
        raise ProductImportError(f"Record {record}: field too large in {header}")
    if isinstance(column.type, (Boolean, Integer, Numeric)):
        value = value.strip()
    if not value:
        if column.name == "handle":
            raise ProductImportError(f"Record {record}: Handle is required")
        return None
    if column.name == "handle" and not value.strip():
        raise ProductImportError(f"Record {record}: Handle is required")
    if isinstance(column.type, Boolean):
        if value.lower() not in {"true", "false"}:
            raise ProductImportError(f"Record {record}: invalid boolean in {header}")
        return value.lower() == "true"
    if isinstance(column.type, Integer):
        if not INTEGER_TEXT.fullmatch(value):
            raise ProductImportError(f"Record {record}: invalid integer in {header}")
        try:
            result = int(value)
        except ValueError as exc:
            raise ProductImportError(f"Record {record}: integer too large in {header}") from exc
        bits = 64 if isinstance(column.type, BigInteger) else 32
        if not -(2 ** (bits - 1)) <= result < 2 ** (bits - 1):
            raise ProductImportError(f"Record {record}: integer out of range in {header}")
        return result
    if isinstance(column.type, Numeric):
        try:
            result = Decimal(value)
        except InvalidOperation as exc:
            raise ProductImportError(f"Record {record}: invalid decimal in {header}") from exc
        if not result.is_finite() or result.adjusted() > 131071 or result.as_tuple().exponent < -16383:
            raise ProductImportError(f"Record {record}: decimal out of range in {header}")
        return result
    return value


def prepare(path: Path, options: ImportOptions | None = None) -> PreparedImport:
    options = options or ImportOptions()
    with path.open("rb") as stream:
        raw = stream.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise ProductImportError("CSV exceeds the 25 MiB file limit")
    file_sha256 = sha256(raw).hexdigest()
    try:
        decoded = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ProductImportError("CSV must use UTF-8 encoding") from exc
    old_limit = csv.field_size_limit(MAX_FIELD_CHARACTERS)
    rows: list[dict[str, object]] = []
    try:
        reader = csv.reader(io.StringIO(decoded, newline=""), strict=True)
        headers = next(reader, [])
        if len(headers) != len(SHOPIFY_COLUMN_MAP) or set(headers) != set(SHOPIFY_COLUMN_MAP):
            raise ProductImportError("CSV headers must contain exactly the 88 supported Shopify fields")
        for record, cells in enumerate(reader, 1):
            if record > MAX_RECORDS:
                raise ProductImportError("CSV exceeds the 10,000-record limit")
            if len(cells) != len(headers):
                raise ProductImportError(f"Record {record}: expected 88 columns")
            row = {SHOPIFY_COLUMN_MAP[header]: _cell(value, header, record)
                   for header, value in zip(headers, cells, strict=True)}
            row.update(
                source_file_name=path.name, source_file_sha256=file_sha256,
                source_row_number=record, source_exported_at=options.exported_at,
                snapshot_currency=options.currency, visibility=options.visibility,
            )
            rows.append(row)
    except csv.Error as exc:
        raise ProductImportError("Invalid CSV quoting or field size") from exc
    finally:
        csv.field_size_limit(old_limit)
    if not rows:
        raise ProductImportError("CSV must contain at least one data record")
    return PreparedImport(path.name, file_sha256, raw, tuple(rows), options)


def _utc(value: object) -> object:
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return value


def verify_rows(db: Session, prepared: PreparedImport) -> None:
    stored = db.execute(select(Product.__table__).where(
        Product.source_file_sha256 == prepared.file_sha256,
    ).order_by(Product.source_row_number)).mappings()
    count = 0
    for count, actual in enumerate(stored, 1):
        if count > len(prepared.rows):
            raise ProductImportError("Stored snapshot contains unexpected records")
        expected = prepared.rows[count - 1]
        for name, value in expected.items():
            if _utc(actual[name]) != _utc(value):
                raise ProductImportError(f"Stored snapshot differs at record {count}, column {name}; no data overwritten")
        if actual["imported_at"] is None:
            raise ProductImportError("Stored snapshot has no import timestamp")
    if count != len(prepared.rows):
        raise ProductImportError("Stored snapshot is incomplete; no data overwritten")


def apply(sessions: sessionmaker[Session], prepared: PreparedImport) -> dict[str, object]:
    with sessions.begin() as db:
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text("SET LOCAL statement_timeout = '15s'"))
            db.execute(text("SET LOCAL lock_timeout = '2s'"))
            # Prevent concurrent imports/manual writes from racing the initial
            # snapshot check. Readers continue; this lock ends at transaction exit.
            db.execute(text("LOCK TABLE products IN SHARE ROW EXCLUSIVE MODE"))
        other = db.scalar(select(Product.id).where(
            Product.source_file_sha256 != prepared.file_sha256,
        ).limit(1))
        if other is not None:
            raise ProductImportError("Products already contain another snapshot; agree a replacement workflow first")
        existing = db.scalar(select(func.count()).select_from(Product))
        if existing:
            verify_rows(db, prepared)
            result = {"status": "verified_unchanged", "inserted_rows": 0, "skipped_rows": existing}
        else:
            for start in range(0, len(prepared.rows), INSERT_BATCH_SIZE):
                db.execute(insert(Product.__table__), prepared.rows[start:start + INSERT_BATCH_SIZE])
            verify_rows(db, prepared)
            result = {"status": "imported", "inserted_rows": len(prepared.rows), "skipped_rows": 0}
    return prepared.summary() | result | {"verified_rows": len(prepared.rows)}


def preserve_original(prepared: PreparedImport, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = directory / f"{prepared.file_sha256}.csv"
    try:
        with target.open("xb") as stream:
            target.chmod(0o600)
            stream.write(prepared.original)
    except FileExistsError:
        with target.open("rb") as stream:
            existing = stream.read(MAX_FILE_BYTES + 1)
        if sha256(existing).hexdigest() != prepared.file_sha256:
            raise ProductImportError("Retained original failed its checksum check")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-sha256")
    parser.add_argument("--exported-at", type=str)
    parser.add_argument("--currency", type=str)
    parser.add_argument("--visibility", choices=("staff", "admin"), default="staff")
    args = parser.parse_args()
    try:
        options = ImportOptions.model_validate({
            "exported_at": args.exported_at, "currency": args.currency, "visibility": args.visibility,
        })
        prepared = prepare(args.input, options)
        result = prepared.summary() | {"status": "preview", "database_changed": False}
        if args.apply:
            if args.expected_sha256 != prepared.file_sha256:
                raise ProductImportError("Apply requires --expected-sha256 matching the previewed file")
            from app.db.session import SessionLocal

            retained = preserve_original(prepared, Path("data/extracted/shopify_products/originals"))
            result = apply(SessionLocal, prepared) | {"retained_original": str(retained)}
        print(json.dumps(result, indent=2))
    except ProductImportError as exc:
        parser.exit(1, f"Product import refused: {exc}\n")
    except ValidationError:
        parser.exit(1, "Product import refused: invalid export time, currency or visibility\n")
    except OSError:
        parser.exit(1, "Product import refused: source or retained-file storage unavailable\n")
    except SQLAlchemyError:
        parser.exit(1, "Product import failed: database operation failed; verify stored snapshot before retrying\n")


if __name__ == "__main__":
    main()
