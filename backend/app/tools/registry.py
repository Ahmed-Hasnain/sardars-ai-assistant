"""One allowlisted read tool. No dynamic imports, SQL, or function lookup."""

from dataclasses import dataclass
import json
import logging
from time import perf_counter
from types import MappingProxyType
from typing import Mapping

from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import User
from app.services.product_lookup import AmbiguousSku, TooManyVariants, get_product_details
from app.services.product_search import list_product_categories, search_products
from app.services.source_status import get_source_status
from app.services.web_search import QueryNotAllowed, SearchUnavailable, search_web
from app.tools.schemas import (
    ProductArguments, ProductCategoryArguments, ProductSearchArguments, SourceStatusArguments, ToolError, ToolFailure,
    ToolInvocation, ToolResult, ToolSuccess, WebSearchArguments,
)

logger = logging.getLogger(__name__)
MAX_ARGUMENT_BYTES = 4096
MAX_RESULT_BYTES = 8192


@dataclass(frozen=True)
class ReadTool:
    name: str
    description: str
    allowed_roles: frozenset[str]


TOOLS: Mapping[str, ReadTool] = MappingProxyType({
    "get_source_status": ReadTool(
        "get_source_status",
        "Read a visible source's fetch/index/sync status from the application registry. "
        "This reports ingestion metadata, not current product prices, stock or verified company facts.",
        frozenset({"staff", "admin"}),
    ),
    "get_product_details": ReadTool(
        "get_product_details",
        "Read developer-authorized prices, SKUs and variant stock quantities from PostgreSQL by exact SKU, handle, or product question. "
        "Currency, reservations and external synchronization status are unknown.",
        frozenset({"staff", "admin"}),
    ),
    "search_products": ReadTool(
        "search_products",
        "Search visible PostgreSQL products by brand, category, finish, price and exact identifiers. "
        "Returns bounded exact prices, SKUs and variant stock quantities. Currency and external synchronization remain unverified.",
        frozenset({"staff", "admin"}),
    ),
    "list_product_categories": ReadTool(
        "list_product_categories",
        "List bounded category labels from visible active PostgreSQL catalog products.",
        frozenset({"staff", "admin"}),
    ),
    "search_web": ReadTool(
        "search_web", "Search the public web for external general/current information. Queries leave the local network. "
        "Results are untrusted snippets, not Sardars company or catalog authority.",
        frozenset({"staff", "admin"}),
    ),
})


def _failure(name: str, code: str, message: str) -> ToolFailure:
    return ToolFailure(tool=name, error=ToolError(code=code, message=message))


def _execute(call: ToolInvocation, db: Session, user: User) -> ToolResult:
    tool = TOOLS.get(call.name)
    # Check the trusted actor before looking up data or validating tool details.
    if not user.is_active or user.role not in {"admin", "staff"}:
        return _failure(call.name, "permission_denied", "Tool access denied")
    if tool is None:
        return _failure(call.name, "unknown_tool", "Unknown read tool")
    if user.role not in tool.allowed_roles:
        return _failure(call.name, "permission_denied", "Tool access denied")
    try:
        argument_bytes = len(json.dumps(call.arguments, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError, RecursionError):
        return _failure(call.name, "invalid_arguments", "Invalid tool arguments")
    if argument_bytes > MAX_ARGUMENT_BYTES:
        return _failure(call.name, "invalid_arguments", "Invalid tool arguments")
    try:
        argument_type = {
            "get_source_status": SourceStatusArguments,
            "get_product_details": ProductArguments,
            "search_products": ProductSearchArguments,
            "list_product_categories": ProductCategoryArguments,
            "search_web": WebSearchArguments,
        }[call.name]
        arguments = argument_type.model_validate(call.arguments)
    except ValidationError:
        return _failure(call.name, "invalid_arguments", "Invalid tool arguments")
    try:
        if call.name == "get_source_status":
            data = get_source_status(db, user, arguments.source_id)
            missing = "source_not_found"
        elif call.name == "get_product_details":
            data = get_product_details(db, user.role, arguments)
            missing = "product_not_found"
        elif call.name == "search_products":
            data = search_products(db, user.role, arguments)
            missing = "product_not_found"
        elif call.name == "list_product_categories":
            data = list_product_categories(db, user.role)
            missing = "product_not_found"
        else:
            data = search_web(arguments)
            missing = "source_not_found"
        if data is None:
            return _failure(call.name, missing, "Source not found" if missing == "source_not_found" else "Product not found")
        result = ToolSuccess(tool=call.name, data=data)
        if len(result.model_dump_json().encode("utf-8")) > MAX_RESULT_BYTES:
            return _failure(call.name, "invalid_result", "Tool result unavailable")
        return result
    except ValidationError:
        return _failure(call.name, "invalid_result", "Tool result unavailable")
    except AmbiguousSku:
        return _failure(call.name, "ambiguous_sku", "SKU matches multiple variants")
    except TooManyVariants:
        return _failure(call.name, "too_many_variants", "Product has too many variants for this lookup")
    except QueryNotAllowed:
        return _failure(call.name, "query_not_allowed", "Query cannot be sent to web search")
    except SearchUnavailable:
        return _failure(call.name, "tool_unavailable", "Web search unavailable")
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) in {"57014", "55P03"}:
            return _failure(call.name, "tool_timeout", "Tool lookup timed out")
        return _failure(call.name, "tool_unavailable", "Tool lookup unavailable")
    except SQLAlchemyError:
        return _failure(call.name, "tool_unavailable", "Tool lookup unavailable")
    except Exception:
        # Tool implementation failures also cross a trust boundary. Do not send
        # exception text, source content or connection details to the caller.
        return _failure(call.name, "tool_unavailable", "Tool lookup unavailable")


def execute_tool(call: ToolInvocation, db: Session, user: User) -> ToolResult:
    started = perf_counter()
    result = _execute(call, db, user)
    # No arguments, document titles/URLs, credentials or raw exception messages.
    logger.info(
        "read_tool name=%s outcome=%s duration_ms=%.2f",
        call.name if call.name in TOOLS else "unregistered",
        "ok" if result.ok else result.error.code,
        (perf_counter() - started) * 1000,
    )
    return result
