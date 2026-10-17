"""Reliable, application-selected product tool path for staff chat."""

import re

from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.db.models import User
from app.rag.text_safety import contains_prompt_instruction
from app.rag.claim_safety import unsafe_catalog_display
from app.schemas.chat import ChatResponse, ProductSource
from app.tools.registry import execute_tool
from app.tools.schemas import ProductCandidates, ProductDetails, ToolInvocation, ToolSuccess

PRODUCT_INTENT = re.compile(r"\b(?:sku|price|prices|pricing|variant|variants|product details|product handle|cost|how much)\b", re.I)
NO_PRODUCT = "I couldn't find a matching product in the current database. Provide a SKU, product handle, or more of the product name."


def _render_product(data: ProductDetails) -> str:
    lines = [f"{data.title or data.handle} (handle: {data.handle})"]
    if data.vendor:
        lines.append(f"Vendor: {data.vendor}")
    lines.append("Current prices and SKUs in the Sardars product database:")
    for variant in data.variants:
        options = ", ".join(
            f"{name}: {value}" for name, value in (
                (variant.option1_name, variant.option1_value),
                (variant.option2_name, variant.option2_value),
                (variant.option3_name, variant.option3_value),
            ) if name and value
        )
        suffix = f" ({options})" if options else ""
        lines.append(f"SKU {variant.sku or 'unknown'}{suffix}: price {variant.price} (currency not recorded)")
        if variant.row_kind == "image_only":
            lines.append("This SKU is on an image-only CSV row, not a product variant.")
    lines.append("Values were read from PostgreSQL at request time. External Shopify/ERP sync and stock are unverified.")
    return "\n".join(lines)


def _render_candidates(data: ProductCandidates) -> str:
    lines = ["Several products match. Please provide a SKU or handle to choose one:"]
    for match in data.matches:
        lines.append(f"- {match.title or match.handle} (handle: {match.handle})")
    if data.more_matches:
        lines.append("More matches exist; please narrow the product name.")
    return "\n".join(lines)


async def answer_product(question: str, user: User, db: Session) -> ChatResponse:
    # Price/SKU questions are routed here by application code. A small model's
    # decision to emit a tool call is not needed for exact database facts.
    call = ToolInvocation(name="get_product_details", arguments={"question": question})
    result = await run_in_threadpool(execute_tool, call, db, user)
    if not isinstance(result, ToolSuccess):
        if result.error.code == "tool_timeout":
            answer = "The product database lookup timed out. Please try again."
        elif result.error.code in {"tool_unavailable", "invalid_result"}:
            answer = "The product database is unavailable right now."
        elif result.error.code == "ambiguous_sku":
            answer = "Several SKUs match that question. Please ask about one SKU at a time."
        elif result.error.code == "too_many_variants":
            answer = "This product has too many variants for one answer. Please ask about a specific SKU."
        else:
            answer = NO_PRODUCT
        return ChatResponse(answer=answer, route="product", model=None)
    if isinstance(result.data, ProductCandidates):
        if any(contains_prompt_instruction(item.title or "") or unsafe_catalog_display(item.title or "")
               for item in result.data.matches):
            return ChatResponse(answer="Product lookup unavailable.", route="product", model=None)
        return ChatResponse(answer=_render_candidates(result.data), route="product", model=None,
                            company_data_verified=True)
    if not isinstance(result.data, ProductDetails):
        return ChatResponse(answer="Product lookup unavailable.", route="product", model=None)
    data = result.data
    display_fields = [data.title or "", data.vendor or "", data.handle]
    for variant in data.variants:
        display_fields.extend(value or "" for value in (
            variant.sku, variant.option1_name, variant.option1_value,
            variant.option2_name, variant.option2_value,
            variant.option3_name, variant.option3_value,
        ))
    if (any(contains_prompt_instruction(value) or unsafe_catalog_display(value)
            for value in display_fields)
        or any(not re.fullmatch(r"\d+(?:\.\d+)?", variant.price) for variant in data.variants)):
        return ChatResponse(answer="Product lookup unavailable.", route="product", model=None)
    source = ProductSource(
        source_file_sha256=data.source_file_sha256,
        database_observed_at=data.observed_at,
        source_exported_at=data.source_exported_at,
        imported_at=data.imported_at,
        currency=data.currency,
    )
    return ChatResponse(answer=_render_product(data), route="product", model=None,
                        company_data_verified=True, product_source=source,
                        product_handles=[data.handle])
