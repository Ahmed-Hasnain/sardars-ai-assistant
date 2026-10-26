"""Role-filtered PostgreSQL reads for developer-authorized product values."""

import re
from datetime import datetime, timezone

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.orm import Session

from app.db.products import Product
from app.rag.text_safety import contains_prompt_instruction
from app.tools.schemas import (
    ProductArguments, ProductCandidate, ProductCandidates, ProductDetails, ProductVariant,
)

MAX_VARIANTS = 32
MAX_CANDIDATES = 5
STOPWORDS = frozenset({
    "a", "about", "all", "and", "any", "are", "available", "can", "cost", "current",
    "details", "do", "does", "for", "have", "how", "i", "in", "is", "its", "me",
    "much", "of", "on", "price", "prices", "pricing", "product", "products", "sardars",
    "show", "sku", "stock", "the", "this", "to", "variant", "variants", "what", "which",
    "with", "you", "your", "please", "give", "get", "tell", "from", "database", "db",
})
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")
EXPLICIT_SKU = re.compile(r"\bsku\s*(?:number|no\.?|#|:|-)?\s*([A-Za-z0-9][A-Za-z0-9._/-]*)", re.I)


class AmbiguousSku(Exception):
    pass


class TooManyVariants(Exception):
    pass


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _display(value: str | None) -> str | None:
    if value is None or contains_prompt_instruction(value) or any(ord(ch) < 32 for ch in value):
        return None
    return value


def _visible(role: str) -> set[str]:
    if role == "staff":
        return {"staff"}
    if role == "admin":
        return {"staff", "admin"}
    return set()


def _columns():
    return (
        Product.handle, Product.title, Product.vendor, Product.variant_sku,
        Product.option1_name, Product.option1_value, Product.option2_name,
        Product.option2_value, Product.option3_name, Product.option3_value,
        Product.variant_price, Product.variant_inventory_qty,
        Product.source_row_kind, Product.source_row_number,
        Product.source_file_sha256, Product.source_exported_at, Product.imported_at,
        Product.snapshot_currency,
    )


def _details(db: Session, allowed: set[str], rows: list, match: str) -> ProductDetails:
    first = rows[0]
    if len({row.source_file_sha256 for row in rows}) != 1:
        raise TooManyVariants()
    # Shopify continuation rows lack identity fields; read the visible title row.
    identity = db.execute(select(
        Product.title, Product.vendor, Product.meta_custom_category, Product.product_type,
    ).where(
        Product.handle == first.handle, Product.visibility.in_(allowed),
        Product.title.is_not(None),
    ).order_by(Product.source_row_number).limit(1)).first()
    title = _display(identity.title) if identity else None
    vendor = _display(identity.vendor) if identity else None
    category = _display(identity.meta_custom_category) if identity else None
    product_type = _display(identity.product_type) if identity else None
    variants = [ProductVariant(
        source_row_number=row.source_row_number, row_kind=row.source_row_kind,
        sku=_display(row.variant_sku),
        option1_name=_display(row.option1_name), option1_value=_display(row.option1_value),
        option2_name=_display(row.option2_name), option2_value=_display(row.option2_value),
        option3_name=_display(row.option3_name), option3_value=_display(row.option3_value),
        price=format(row.variant_price.normalize(), "f"),
        stock_quantity=row.variant_inventory_qty if row.source_row_kind == "variant" else None,
    ) for row in rows]
    return ProductDetails(
        observed_at=datetime.now(timezone.utc), query_match=match,
        handle=first.handle, title=title, vendor=vendor,
        category=category, product_type=product_type,
        source_file_sha256=first.source_file_sha256,
        source_exported_at=_utc(first.source_exported_at),
        imported_at=_utc(first.imported_at), currency=first.snapshot_currency,
        inventory_verified=all(variant.row_kind == "variant" and variant.stock_quantity is not None
                               for variant in variants),
        variants=variants,
    )


def _by_handle(db: Session, allowed: set[str], handle: str, match: str) -> ProductDetails | None:
    rows = db.execute(select(*_columns()).where(
        Product.visibility.in_(allowed), Product.source_row_kind == "variant",
        func.lower(Product.handle) == handle.casefold(),
    ).order_by(Product.source_row_number).limit(MAX_VARIANTS + 1)).all()
    if not rows:
        return None
    if len(rows) > MAX_VARIANTS:
        raise TooManyVariants()
    if any(row.variant_sku is None or row.variant_price is None for row in rows):
        return None
    return _details(db, allowed, rows, match)


def _by_sku(db: Session, allowed: set[str], sku: str) -> ProductDetails | None:
    rows = db.execute(select(*_columns()).where(
        Product.visibility.in_(allowed),
        Product.source_row_kind.in_(("variant", "image_only")),
        func.lower(Product.variant_sku) == sku.casefold(),
    ).limit(2)).all()
    if len(rows) > 1:
        raise AmbiguousSku()
    if not rows:
        return None
    if rows[0].variant_price is None:
        return None
    return _details(db, allowed, rows, "sku")


def _from_question(db: Session, allowed: set[str], question: str) -> ProductDetails | ProductCandidates | None:
    tokens = list(dict.fromkeys(token.lower() for token in TOKEN.findall(question)))[:60]
    explicit = EXPLICIT_SKU.search(question)
    sku_candidates = [explicit.group(1).lower()] if explicit else []
    sku_candidates += [token for token in tokens if len(token) >= 4 and any(ch.isdigit() for ch in token)]
    sku_candidates = list(dict.fromkeys(sku_candidates))[:20]
    if sku_candidates:
        skus = db.execute(select(Product.variant_sku).where(
            Product.visibility.in_(allowed), Product.source_row_kind.in_(("variant", "image_only")),
            func.lower(Product.variant_sku).in_(sku_candidates),
        ).limit(3)).scalars().all()
        if len(skus) > 1:
            raise AmbiguousSku()
        if skus:
            return _by_sku(db, allowed, skus[0])
    # A handle embedded in a question remains an exact identifier.
    handles = db.execute(select(Product.handle).where(
        Product.visibility.in_(allowed), Product.source_row_kind == "variant",
        func.lower(Product.handle).in_(tokens),
    ).distinct().limit(3)).scalars().all()
    if len(handles) > 1:
        raise AmbiguousSku()
    if handles:
        return _by_handle(db, allowed, handles[0], "handle")
    words = list(dict.fromkeys(
        word.lower() for word in re.findall(r"[A-Za-z0-9]+", question)
        if len(word) >= 3 and word.lower() not in STOPWORDS
    ))[:6]
    if not words:
        return None
    conditions = [or_(
        func.lower(Product.title).contains(word, autoescape=True),
        func.lower(Product.handle).contains(word, autoescape=True),
    ) for word in words]
    matches = db.execute(select(Product.handle, Product.title).where(
        Product.visibility.in_(allowed), Product.source_row_kind == "variant",
        Product.title.is_not(None), and_(*conditions),
    ).distinct().order_by(Product.handle).limit(MAX_CANDIDATES + 1)).all()
    if len(matches) == 1:
        return _by_handle(db, allowed, matches[0].handle, "name")
    if len(matches) > 1:
        return ProductCandidates(
            observed_at=datetime.now(timezone.utc),
            matches=[ProductCandidate(handle=row.handle, title=_display(row.title))
                     for row in matches[:MAX_CANDIDATES]],
            more_matches=len(matches) > MAX_CANDIDATES,
        )
    return None


def get_product_details(db: Session, role: str, args: ProductArguments) -> ProductDetails | ProductCandidates | None:
    allowed = _visible(role)
    if not allowed:
        return None
    with db.no_autoflush:
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text("SET LOCAL statement_timeout = '2s'"))
            db.execute(text("SET LOCAL lock_timeout = '1s'"))
        if args.question is not None:
            return _from_question(db, allowed, args.question)
        assert args.identifier is not None  # enforced by the strict schema
        by_sku = _by_sku(db, allowed, args.identifier)
        if by_sku is not None:
            competing = _by_handle(db, allowed, args.identifier, "handle")
            if competing is not None and competing.handle != by_sku.handle:
                raise AmbiguousSku()
            return by_sku
        return _by_handle(db, allowed, args.identifier, "handle")
