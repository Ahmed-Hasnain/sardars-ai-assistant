"""Bounded catalog search for combined structured and descriptive answers."""

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import and_, exists, func, or_, select, text
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session, aliased

from app.db.models import SourceRegistration
from app.db.products import Product
from app.services.product_lookup import _display, _visible
from app.tools.schemas import ProductSearchArguments, ProductSearchMatch, ProductSearchResults

MAX_PRODUCTS = 3
MAX_VARIANTS_PER_PRODUCT = 32
MAX_TERMS = 6
PRODUCT_URL = "https://sardarandco.com/products/"
PRICE_LIMIT = re.compile(r"\b(under|below|less than|up to|at most|over|above|more than|at least)\s*(?:(pkr|rs\.?|usd|\$)\s*)?([0-9][0-9,]*(?:\.[0-9]{1,2})?)\b", re.I)
PRICE_BETWEEN = re.compile(r"\bbetween\s*(?:(?:pkr|rs\.?|usd|\$)\s*)?([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s+and\s*(?:(?:pkr|rs\.?|usd|\$)\s*)?([0-9][0-9,]*(?:\.[0-9]{1,2})?)\b", re.I)
CURRENCY = re.compile(r"\b(?:pkr|rs\.?|usd)\b|\$", re.I)
TOKEN = re.compile(r"[a-z0-9][a-z0-9-]*", re.I)
EXPLICIT_HANDLE = re.compile(r"\bhandle\s*(?:#|:)?\s*([A-Za-z0-9][A-Za-z0-9-]*)", re.I)
EXPLICIT_SKU = re.compile(r"\bsku\s*(?:#|:)?\s*([A-Za-z0-9][A-Za-z0-9-]*)", re.I)
COMPARE_NAMES = re.compile(r"^\s*compare\s+(.+?)\s+(?:and|vs\.?|versus)\s+(.+?)\s*\??$", re.I)
STOP = frozenset({
    "a", "about", "all", "and", "any", "are", "at", "available", "can", "cheaper", "compare",
    "cost", "difference", "do", "does", "for", "from", "have", "how", "i", "in", "is", "me",
    "more", "much", "of", "or", "our", "please", "price", "prices", "product", "products",
    "recommend", "recommendation", "sardar", "sardars", "show", "sku", "suggest", "than", "the",
    "their", "these", "this", "to", "under", "which", "with", "you", "your", "what", "would",
    "be", "best", "better", "one", "ones", "them", "those", "details", "tell", "give", "list",
    "pkr", "rs", "usd", "between", "below", "above", "least", "most", "up", "less", "over",
})
FINISH_TERMS = frozenset({"black", "white", "chrome", "gold", "silver", "gunmetal", "bronze", "copper"})
PRODUCT_TYPE_TERMS = frozenset({"basin", "mixer", "shower", "bath", "toilet", "sink", "faucet", "tap", "tile", "vanity"})


def _price_filter(question: str) -> tuple[Decimal | None, Decimal | None, str | None, bool, bool]:
    minimum = maximum = None
    min_inclusive = max_inclusive = False
    currency = CURRENCY.search(question)
    requested_currency = None
    if currency:
        requested_currency = "USD" if currency.group().lower() in {"usd", "$"} else "PKR"
    between = PRICE_BETWEEN.search(question)
    if between:
        try:
            minimum = Decimal(between.group(1).replace(",", ""))
            maximum = Decimal(between.group(2).replace(",", ""))
            min_inclusive = max_inclusive = True
        except InvalidOperation:
            minimum = maximum = None
    for match in PRICE_LIMIT.finditer(question):
        try:
            amount = Decimal(match.group(3).replace(",", ""))
        except InvalidOperation:
            continue
        if amount <= 0 or amount > Decimal("1000000000"):
            continue
        phrase = match.group(1).lower()
        if phrase in {"under", "below", "less than", "up to", "at most"}:
            inclusive = phrase in {"up to", "at most"}
            if maximum is None or amount < maximum or (amount == maximum and not inclusive):
                maximum, max_inclusive = amount, inclusive
        else:
            inclusive = phrase == "at least"
            if minimum is None or amount > minimum or (amount == minimum and not inclusive):
                minimum, min_inclusive = amount, inclusive
    return minimum, maximum, requested_currency, min_inclusive, max_inclusive


def _terms(question: str) -> list[str]:
    without_price = PRICE_BETWEEN.sub(" ", PRICE_LIMIT.sub(" ", question))
    return list(dict.fromkeys(
        (word[:-1] if word.endswith("s") and not word.endswith("ss") and len(word) > 4 else word)
        for word in TOKEN.findall(without_price.casefold().replace("-", " "))
        if len(word) >= 3 and word not in STOP and not word.isdecimal()
    ))[:MAX_TERMS]


def _term_exists(handle_column, allowed: set[str], term: str):
    row = aliased(Product)
    if term in FINISH_TERMS:
        fields = (row.title, row.handle, row.option1_value, row.option2_value, row.option3_value)
    elif term in PRODUCT_TYPE_TERMS:
        fields = (row.title, row.handle)
    else:
        fields = (row.title, row.handle, row.vendor, row.product_category, row.meta_custom_category,
                  row.meta_custom_sub_category, row.meta_shopify_mounting_type,
                  row.option1_value, row.option2_value, row.option3_value)
    return exists(select(1).where(
        row.handle == handle_column, row.visibility.in_(allowed),
        or_(*(func.lower(field).contains(term, autoescape=True) for field in fields)),
    ))


def _specifications(variant: Row, identity: Row) -> dict[str, str]:
    specs: dict[str, str] = {}
    for name, value in (
        (variant.option1_name or identity.option1_name, variant.option1_value),
        (variant.option2_name or identity.option2_name, variant.option2_value),
        (variant.option3_name or identity.option3_name, variant.option3_value),
    ):
        clean_name, clean_value = _display(name), _display(value)
        if clean_name and clean_value and len(clean_name) <= 40 and len(clean_value) <= 100:
            specs[clean_name] = clean_value
    for name, value in (
        ("Material", identity.meta_shopify_material),
        ("Mounting type", identity.meta_shopify_mounting_type),
        ("Size", identity.meta_shopify_size),
    ):
        clean = _display(value)
        if clean and len(clean) <= 100 and ";" not in clean and name not in specs:
            specs[name] = clean
    return dict(list(specs.items())[:6])


def search_products(db: Session, role: str, args: ProductSearchArguments) -> ProductSearchResults:
    allowed = _visible(role)
    observed_at = datetime.now(timezone.utc)
    empty = lambda **kw: ProductSearchResults(observed_at=observed_at, matches=[], **kw)
    if not allowed:
        return empty()
    minimum, maximum, currency, min_inclusive, max_inclusive = _price_filter(args.question)
    context = list(dict.fromkeys(args.context_handles))
    if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}", handle) for handle in context):
        return empty()
    if ((PRICE_LIMIT.search(args.question) or PRICE_BETWEEN.search(args.question))
            and minimum is None and maximum is None):
        return empty()
    if any(value is not None and (value <= 0 or value > Decimal("1000000000"))
           for value in (minimum, maximum)):
        return empty()
    if minimum is not None and maximum is not None and minimum > maximum:
        return empty()
    with db.no_autoflush:
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text("SET LOCAL statement_timeout = '2s'"))
            db.execute(text("SET LOCAL lock_timeout = '1s'"))

        # Explicit handles in the question and client-provided follow-up handles
        # are always rechecked against the user's visibility in the queries below.
        tokens = TOKEN.findall(args.question.casefold())[:60]
        handle_candidates = [token for token in tokens if len(token) >= 8 and token.count("-") >= 2]
        handle_candidates += [match.group(1).casefold() for match in EXPLICIT_HANDLE.finditer(args.question)]
        embedded = db.scalars(select(Product.handle).where(
            Product.visibility.in_(allowed), Product.source_row_kind == "variant",
            func.lower(Product.handle).in_(handle_candidates[:20]),
        ).distinct().limit(MAX_PRODUCTS + 1)).all()
        sku_candidates = [match.group(1).casefold() for match in EXPLICIT_SKU.finditer(args.question)]
        sku_candidates += [token for token in tokens if len(token) >= 5 and any(char.isdigit() for char in token)]
        sku_rows = db.execute(select(Product.handle, Product.variant_sku).where(
            Product.visibility.in_(allowed), Product.source_row_kind == "variant",
            func.lower(Product.variant_sku).in_(sku_candidates[:20]),
        ).distinct().limit(MAX_PRODUCTS + 1)).all()
        exact_skus: dict[str, set[str]] = {}
        for handle, sku in sku_rows:
            exact_skus.setdefault(handle, set()).add(sku.casefold())
        named_handles: list[str] = []
        named = COMPARE_NAMES.fullmatch(args.question) if not exact_skus and not embedded and not context else None
        if named:
            for part in named.groups():
                part_terms = _terms(part)
                if not part_terms:
                    break
                identity_query = select(Product.handle).where(
                    Product.visibility.in_(allowed), Product.source_row_kind == "variant",
                    Product.status == "active", Product.title.is_not(None),
                )
                candidates = db.scalars(identity_query.where(
                    func.lower(Product.title).contains(part.strip().casefold(), autoescape=True)
                ).distinct().limit(2)).all()
                if not candidates:
                    candidates = db.scalars(identity_query.where(
                        *(func.lower(Product.title).contains(word, autoescape=True) for word in part_terms),
                    ).distinct().limit(2)).all()
                if len(candidates) != 1:
                    named_handles = []
                    break
                named_handles.append(candidates[0])
        handles = list(dict.fromkeys([*context, *embedded, *exact_skus, *named_handles]))[:MAX_PRODUCTS]
        term_question = args.question
        for identifier in [*embedded, *(sku for _, sku in sku_rows)]:
            term_question = re.sub(re.escape(identifier), " ", term_question, flags=re.I)
        terms = _terms(term_question)
        finishes = [term for term in terms if term in FINISH_TERMS]
        if not handles and not terms:
            return empty(currency_unverified=bool(currency))

        base = select(Product.handle).where(
            Product.visibility.in_(allowed), Product.source_row_kind == "variant",
            Product.status == "active", Product.title.is_not(None),
        )
        if handles:
            base = base.where(Product.handle.in_(handles))
        else:
            for term in terms:
                base = base.where(_term_exists(Product.handle, allowed, term))
        priced = aliased(Product)
        price_conditions = [
            priced.handle == Product.handle, priced.visibility.in_(allowed),
            priced.source_row_kind == "variant", priced.variant_sku.is_not(None),
            priced.variant_price.is_not(None),
        ]
        if minimum is not None:
            price_conditions.append(priced.variant_price >= minimum if min_inclusive else priced.variant_price > minimum)
        if maximum is not None:
            price_conditions.append(priced.variant_price <= maximum if max_inclusive else priced.variant_price < maximum)
        option_fields = (priced.option1_value, priced.option2_value, priced.option3_value)
        has_named_finish = or_(*(
            func.lower(field).contains(color, autoescape=True)
            for field in option_fields for color in FINISH_TERMS
        ))
        for finish in finishes:
            selected_finish = func.coalesce(or_(*(
                func.lower(field).contains(finish, autoescape=True) for field in option_fields
            )), False)
            identity_finish = or_(
                func.lower(Product.title).contains(finish, autoescape=True),
                func.lower(Product.handle).contains(finish, autoescape=True),
            )
            price_conditions.append(or_(selected_finish, and_(~func.coalesce(has_named_finish, False), identity_finish)))
        if currency is not None:
            priced_for_currency = [*price_conditions, priced.snapshot_currency == currency]
            missing_currency = db.scalar(base.where(exists(select(1).where(
                and_(*price_conditions, priced.snapshot_currency.is_(None))
            ))).limit(1)) is not None
        else:
            priced_for_currency = price_conditions
            missing_currency = False
        base = base.where(exists(select(1).where(and_(*priced_for_currency))))
        candidate_query = base
        if args.prefer_descriptions:
            source_visibility = {"public", "staff", "admin"} if role == "admin" else {"public", "staff"}
            described = base.join(SourceRegistration, SourceRegistration.url == PRODUCT_URL + Product.handle).where(
                SourceRegistration.source_type == "products", SourceRegistration.is_active.is_(True),
                SourceRegistration.index_status == "ready", SourceRegistration.visibility.in_(source_visibility),
            )
            if db.scalar(described.limit(1)) is not None:
                candidate_query = described
        candidate_handles = db.scalars(candidate_query.distinct().order_by(Product.handle).limit(MAX_PRODUCTS + 1)).all()

        results: list[ProductSearchMatch] = []
        extra_variant_matches = False
        for handle in candidate_handles[:MAX_PRODUCTS]:
            rows = db.execute(select(
                Product.handle, Product.title, Product.vendor, Product.variant_sku,
                Product.variant_price, Product.snapshot_currency, Product.source_file_sha256,
                Product.option1_name, Product.option1_value, Product.option2_name,
                Product.option2_value, Product.option3_name, Product.option3_value,
            ).where(
                Product.handle == handle, Product.visibility.in_(allowed),
                Product.source_row_kind == "variant", Product.variant_sku.is_not(None),
                Product.variant_price.is_not(None),
            ).order_by(Product.variant_price, Product.source_row_number).limit(MAX_VARIANTS_PER_PRODUCT + 1)).all()
            if not rows or len(rows) > MAX_VARIANTS_PER_PRODUCT or len({row.source_file_sha256 for row in rows}) != 1:
                continue
            identity = db.execute(select(
                Product.title, Product.vendor, Product.option1_name, Product.option2_name,
                Product.option3_name, Product.meta_shopify_material,
                Product.meta_shopify_mounting_type, Product.meta_shopify_size,
            ).where(
                Product.handle == handle, Product.visibility.in_(allowed), Product.title.is_not(None),
            ).order_by(Product.source_row_number).limit(1)).first()
            if identity is None:
                continue
            product_title = _display(identity.title)
            def _variant_has_finish(row: Row) -> bool:
                if not finishes:
                    return True
                option_text = " ".join(value or "" for value in
                                       (row.option1_value, row.option2_value, row.option3_value)).casefold()
                identity_text = f"{product_title or ''} {handle}".casefold()
                if any(color in option_text for color in FINISH_TERMS):
                    return all(term in option_text for term in finishes)
                return all(term in option_text or term in identity_text for term in finishes)
            eligible = [row for row in rows if
                        (currency is None or row.snapshot_currency == currency)
                        and (minimum is None or (row.variant_price >= minimum if min_inclusive else row.variant_price > minimum))
                        and (maximum is None or (row.variant_price <= maximum if max_inclusive else row.variant_price < maximum))
                        and _variant_has_finish(row)]
            if handle in exact_skus:
                eligible = [row for row in eligible if row.variant_sku.casefold() in exact_skus[handle]]
            if not eligible:
                continue
            chosen_rows = eligible if handle in exact_skus else eligible[:1]
            for chosen in chosen_rows:
                if len(results) >= MAX_PRODUCTS:
                    extra_variant_matches = True
                    break
                title = _display(chosen.title) or product_title
                vendor = _display(chosen.vendor) or _display(identity.vendor)
                sku = _display(chosen.variant_sku)
                if not title or not sku:
                    continue
                results.append(ProductSearchMatch(
                    handle=handle, title=title, vendor=vendor, sku=sku,
                    price=format(chosen.variant_price.normalize(), "f"), currency=chosen.snapshot_currency,
                    source_file_sha256=chosen.source_file_sha256,
                    variant_count=1 if handle in exact_skus else len(eligible),
                    specifications=_specifications(chosen, identity),
                ))
        return ProductSearchResults(
            observed_at=observed_at, matches=results,
            more_matches=len(candidate_handles) > MAX_PRODUCTS or extra_variant_matches,
            currency_unverified=missing_currency,
        )
