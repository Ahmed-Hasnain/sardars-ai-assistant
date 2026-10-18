"""Combine exact PostgreSQL catalog matches with authorized product-page excerpts."""

import asyncio
import re

import httpx
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.db.models import User
from app.rag.answer_seed import _approved_excerpts
from app.rag.claim_safety import unsafe_catalog_display, unsafe_descriptive_claim
from app.rag.text_safety import contains_prompt_instruction
from app.retrieval.authorization import authorized_points
from app.retrieval.search_seed import fetch_product_points
from app.schemas.ask import SourceCitation
from app.schemas.chat import ChatResponse, MatchedProduct
from app.services.product_search import FINISH_TERMS, PRODUCT_URL
from app.tools.registry import execute_tool
from app.tools.schemas import ProductSearchResults, ToolInvocation, ToolSuccess

CHANGING_CLAIM = re.compile(r"\b(?:price|prices|priced|stock|inventory|available|availability|sale|discount|pkr|usd|rs\.)\b|[$₨]", re.I)
NON_DESCRIPTION = re.compile(r"^(?:article numbers?|art no\.?|net weight|frequently asked questions)\b", re.I)
COMPARISON = re.compile(r"\b(?:compare|comparison|difference|cheaper|lowest|less expensive)\b", re.I)
RECOMMENDATION = re.compile(r"\b(?:recommend|suggest)\b", re.I)


def _description(points: list[dict], url: str, specifications: dict[str, str]) -> tuple[str, SourceCitation] | None:
    matching_points = [point for point in points if point.get("payload", {}).get("url") == url]
    matching_points.sort(key=lambda point: point.get("payload", {}).get("chunk_index", 999))
    expected_finishes = {value.casefold() for name, value in specifications.items()
                         if name.casefold() in {"finish", "color", "colour"} and value.casefold() in FINISH_TERMS}
    for excerpt in _approved_excerpts(matching_points):
        if excerpt.url != url:
            continue
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", excerpt.text):
            sentence = sentence.strip()
            mentioned_finishes = {color for color in FINISH_TERMS
                                  if re.search(rf"\b{re.escape(color)}\b", sentence, re.I)}
            if (40 <= len(sentence) <= 320 and not contains_prompt_instruction(sentence)
                    and not unsafe_descriptive_claim(sentence)
                    and not CHANGING_CLAIM.search(sentence) and not NON_DESCRIPTION.search(sentence)
                    and (not expected_finishes or not mentioned_finishes
                         or bool(expected_finishes & mentioned_finishes))):
                return sentence, SourceCitation(
                    number=0, source_id=excerpt.source_id, title=excerpt.title,
                    url=excerpt.url, fetched_at=excerpt.fetched_at,
                    content_derivation=excerpt.content_derivation,
                    original_content_sha256=excerpt.original_content_sha256,
                )
    return None


async def answer_product_discovery(
    question: str, user: User, db: Session, context_handles: list[str] | None = None,
) -> ChatResponse:
    call = ToolInvocation(name="search_products", arguments={
        "question": question, "context_handles": context_handles or [],
        "prefer_descriptions": bool(RECOMMENDATION.search(question) and not context_handles),
    })
    result = await run_in_threadpool(execute_tool, call, db, user)
    if not isinstance(result, ToolSuccess) or not isinstance(result.data, ProductSearchResults):
        return ChatResponse(answer="The product search is unavailable right now.", route="product_search", model=None)
    data = result.data
    if not data.matches:
        answer = ("I can't apply that currency filter because the product database has no verified currency for these matches."
                  if data.currency_unverified else
                  "I couldn't verify matching active products with those filters. Try a brand, category, handle, or SKU.")
        return ChatResponse(answer=answer, route="product_search", model=None)

    if any(
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,199}", item.handle)
        or not re.fullmatch(r"\d+(?:\.\d+)?", item.price)
        or (item.stock_quantity is not None and item.stock_quantity < 0)
        or any(contains_prompt_instruction(value) or unsafe_catalog_display(value) for value in (
            item.title, item.sku, item.vendor or "", *item.specifications.keys(),
            *item.specifications.values(),
        ))
        for item in data.matches
    ):
        return ChatResponse(answer="The product search is unavailable right now.", route="product_search", model=None)

    urls = list(dict.fromkeys(
        PRODUCT_URL + item.handle for item in data.matches
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,199}", item.handle)
    ))
    points: list[dict] = []
    if urls:
        try:
            raw = await asyncio.to_thread(fetch_product_points, urls, user.role)
            points = authorized_points(db, user.role, raw)
        except (httpx.HTTPError, ValueError, KeyError, TypeError, SQLAlchemyError):
            # A failed description index must not turn a database match into a
            # fabricated product description or hide a verified price/SKU.
            points = []

    lines = ["Matching products in the current Sardars product database:"]
    products: list[MatchedProduct] = []
    sources: list[SourceCitation] = []
    for match in data.matches:
        url = PRODUCT_URL + match.handle
        excerpt = _description(points, url, match.specifications)
        source_id = None
        if excerpt:
            description, citation = excerpt
            existing = next((source for source in sources if source.source_id == citation.source_id), None)
            if existing:
                citation = existing
            else:
                citation.number = len(sources) + 1
                sources.append(citation)
            source_id = citation.source_id
        lines.append(
            f"{match.title} (handle: {match.handle}): lowest qualifying variant SKU {match.sku}, "
            f"price {match.price} {match.currency or '(currency not recorded)'}; "
            f"database stock {match.stock_quantity} units."
            if match.stock_quantity is not None else
            f"{match.title} (handle: {match.handle}): lowest qualifying variant SKU {match.sku}, "
            f"price {match.price} {match.currency or '(currency not recorded)'}; database stock not recorded."
        )
        if match.specifications:
            lines.append("Catalog-listed specifications: " + ", ".join(
                f"{name}: {value}" for name, value in match.specifications.items()
            ) + ".")
        if excerpt:
            lines.append(f"Description from its registered product page: {description} [{citation.number}]")
        else:
            lines.append("No verified description is available for this catalog match.")
        products.append(MatchedProduct(
            handle=match.handle, title=match.title, sku=match.sku, price=match.price,
            stock_quantity=match.stock_quantity,
            currency=match.currency, database_observed_at=data.observed_at,
            source_file_sha256=match.source_file_sha256, variant_count=match.variant_count,
            specifications=match.specifications,
            description_source_id=source_id,
        ))

    if COMPARISON.search(question) and len(products) >= 2:
        from decimal import Decimal
        currencies = {product.currency for product in products}
        if len(currencies) > 1:
            lines.append("I cannot compare the prices across different or unknown currencies.")
        else:
            cheapest = min(products, key=lambda product: Decimal(product.price))
            lines.append(f"Among the displayed variants, SKU {cheapest.sku} for {cheapest.handle} has the lowest database price value.")
    if data.more_matches:
        lines.append("More catalog matches exist. Narrow the request to see them.")
    if data.currency_unverified:
        lines.append("Some otherwise matching rows lacked the requested currency and were excluded.")
    if not sources:
        lines.append("No matching registered product description was available, so I cannot make a description-based recommendation.")
    lines.append("Prices, SKUs and stock quantities were read from PostgreSQL at request time. Stock can change after this read; reservations and external synchronization are unverified.")
    return ChatResponse(
        answer="\n".join(lines), route="product_search", model=None,
        company_data_verified=True, sources=sources, products=products,
        product_handles=list(dict.fromkeys(item.handle for item in products)),
    )
