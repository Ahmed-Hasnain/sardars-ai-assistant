"""Serial, read-only chat-service baseline; excludes HTTP auth, history and UI."""

import argparse
import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
from statistics import median
import subprocess
from time import perf_counter
from typing import Literal

from fastapi import HTTPException
import httpx
from pydantic import Field, model_validator
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.answer_deadlines import within_answer_deadline
from app.api.chat import _answer_chat
from app.core.config import Settings
from app.db.models import SourceRegistration, User
from app.db.products import Product
from app.db.session import SessionLocal
from app.evaluation.observe_chat import Observation, observe
from app.evaluation.run_coverage import Case, evaluate as evaluate_control
from app.llm.base import ChatModel, ModelError
from app.llm.ollama import OllamaChatModel
from app.rag.answer_seed import FALLBACK
from app.retrieval.seed_config import COLLECTION, MODEL
from app.schemas.chat import ChatRequest, ChatResponse

CASES_PATH = Path(__file__).with_name("chat_cases.json")
ToolName = Literal["get_product_details", "search_products", "get_source_status", "list_product_categories", "search_web"]


class ChatCase(Case):
    category: str = Field(min_length=1, max_length=60)
    answer_not_contains: list[str] = Field(default_factory=list, max_length=10)
    expected_route: Literal["general", "company", "product", "product_search", "out_of_scope"]
    expected_tools: list[ToolName] = Field(default_factory=list, max_length=5)
    expected_tool_error: Literal["product_not_found"] | None = None
    expected_sku: str | None = Field(default=None, max_length=200)
    expected_stock_sku: str | None = Field(default=None, max_length=200)
    stock_filter: Literal["positive", "zero"] | None = None
    min_products: int = Field(default=0, ge=0, le=3)
    min_citations: int = Field(default=0, ge=0, le=3)
    max_citations: int | None = Field(default=None, ge=0, le=3)
    price_under: int | None = Field(default=None, gt=0)
    abstain: bool = False

    @model_validator(mode="after")
    def check_expectations(self):
        if self.control == "routing_general":
            raise ValueError("Use a live general case to measure an answer")
        if self.abstain and self.expected_source:
            raise ValueError("An abstention cannot require a citation")
        if self.expected_sku and self.expected_route != "product":
            raise ValueError("Exact SKU assertions require the product route")
        if self.expected_stock_sku and self.expected_route != "product":
            raise ValueError("Exact stock assertions require the product route")
        if self.stock_filter and self.expected_route != "product_search":
            raise ValueError("Stock filters require the product search route")
        return self


def load_cases(path: Path) -> list[ChatCase]:
    with path.open("rb") as stream:
        raw = stream.read(64 * 1024 + 1)
    if len(raw) > 64 * 1024:
        raise ValueError("Evaluation case file exceeds the size limit")
    try:
        data = json.loads(raw)
        if not isinstance(data, list) or not 1 <= len(data) <= 60:
            raise ValueError("Select one through sixty cases")
        cases = [ChatCase.model_validate(row) for row in data]
        if len({case.id for case in cases}) != len(cases):
            raise ValueError("Case IDs must be unique")
        return cases
    except (ValueError, RecursionError) as exc:
        raise ValueError("Invalid chat evaluation cases") from exc


def exact_facts(case: ChatCase, response: ChatResponse, db: Session) -> bool | None:
    """Independent SQL reference, not the tool's own result as its oracle."""
    if not case.expected_sku and not response.products:
        return None
    allowed = {"staff", "admin"} if case.role == "admin" else {"staff"}
    if case.expected_sku:
        rows = db.scalars(select(Product).where(
            Product.variant_sku == case.expected_sku, Product.visibility.in_(allowed),
        ).limit(2)).all()
        if len(rows) != 1 or rows[0].variant_price is None or response.product_source is None:
            return False
        row = rows[0]
        price = format(row.variant_price.normalize(), "f")
        return bool(
            re.search(rf"SKU {re.escape(row.variant_sku)}(?:\s|\(|:)", response.answer)
            and re.search(rf"price {re.escape(price)}(?![\d.])", response.answer)
            and response.product_handles == [row.handle]
            and response.company_data_verified
            and response.product_source.source_file_sha256 == row.source_file_sha256
            and response.product_source.currency == row.snapshot_currency
            and response.product_source.database_observed_at is not None
        )
    for product in response.products:
        rows = db.scalars(select(Product).where(
            Product.handle == product.handle, Product.variant_sku == product.sku,
            Product.source_file_sha256 == product.source_file_sha256,
            Product.visibility.in_(allowed),
            Product.source_row_kind == "variant",
        ).limit(2)).all()
        # Shopify continuation variants can have NULL status/title. The active
        # visible product identity lives on another row under the same handle.
        active_identity = db.scalar(select(Product.id).where(
            Product.handle == product.handle, Product.visibility.in_(allowed),
            Product.status == "active", Product.source_row_kind == "variant",
            Product.title.is_not(None),
        ).limit(1))
        if (len(rows) != 1 or rows[0].variant_price is None
            or active_identity is None
            or product.price != format(rows[0].variant_price.normalize(), "f")
            or product.currency != rows[0].snapshot_currency
            or not response.company_data_verified
            or not re.search(rf"handle: {re.escape(product.handle)}\):[^\n]*SKU {re.escape(product.sku)}, "
                             rf"price {re.escape(product.price)}(?![\d.])", response.answer)):
            return False
    return True


def stock_facts(case: ChatCase, response: ChatResponse, db: Session) -> bool | None:
    """Check stock against current role-visible PostgreSQL rows, including zero."""
    if not case.expected_stock_sku and not response.products and not case.stock_filter:
        return None
    allowed = {"staff", "admin"} if case.role == "admin" else {"staff"}
    if case.expected_stock_sku:
        rows = db.scalars(select(Product).where(
            Product.variant_sku == case.expected_stock_sku,
            Product.visibility.in_(allowed),
        ).limit(2)).all()
        if len(rows) != 1 or response.product_source is None:
            return False
        row = rows[0]
        quantity = row.variant_inventory_qty if row.source_row_kind == "variant" else None
        if quantity is None:
            return (not response.product_source.current_stock_verified
                    and "database stock not recorded" in response.answer)
        return bool(
            quantity >= 0 and response.product_source.current_stock_verified
            and response.product_source.database_observed_at is not None
            and re.search(rf"SKU {re.escape(row.variant_sku)}(?:\s|\(|:).*?database stock {quantity} units\b",
                          response.answer)
        )
    if case.stock_filter and not response.products:
        return False
    for product in response.products:
        rows = db.scalars(select(Product).where(
            Product.handle == product.handle, Product.variant_sku == product.sku,
            Product.visibility.in_(allowed), Product.source_row_kind == "variant",
        ).limit(2)).all()
        if len(rows) != 1 or rows[0].variant_inventory_qty != product.stock_quantity:
            return False
        quantity = product.stock_quantity
        if quantity is None or quantity < 0:
            if case.stock_filter:
                return False
            if "database stock not recorded" not in response.answer:
                return False
        elif not re.search(rf"SKU {re.escape(product.sku)},[^\n]*database stock {quantity} units\b",
                           response.answer):
            return False
        if case.stock_filter == "positive" and (quantity is None or quantity <= 0):
            return False
        if case.stock_filter == "zero" and quantity != 0:
            return False
    return True


def check_response(case: ChatCase, response: ChatResponse, observation: Observation, db: Session) -> dict:
    permitted = {(row["source_id"], row["url"]) for row in observation.authorized_sources}
    web_urls = {row["url"] for row in observation.web_results}
    markers = {int(value) for value in re.findall(r"\[(\d+)\]", response.answer)}
    checks = {
        "routing": response.route == case.expected_route,
        "tool_selection": [row["name"] for row in observation.tools] == case.expected_tools,
        "tools": (all(row["error_code"] == case.expected_tool_error for row in observation.tools)
                  if observation.tools else None),
        "service": not any(row.get("error_type") for row in observation.retrieval + observation.model_calls),
        "retrieval": (case.expected_source in {row["url"] for row in observation.authorized_sources}
                      if case.expected_source else None),
        "citations": (markers == {source.number for source in response.sources}
                      and all(((source.source_id, source.url) in permitted if source.origin == "company" else
                               source.url in web_urls and source.source_id.startswith("web:"))
                              for source in response.sources)),
        "web_provenance": (all(source.origin == "web" for source in response.sources)
                           if "search_web" in case.expected_tools else None),
        "max_citations": len(response.sources) <= case.max_citations if case.max_citations is not None else None,
        "expected_source": (case.expected_source in {source.url for source in response.sources}
                            if case.expected_source else None),
        "answer": (all(phrase.casefold() in response.answer.casefold() for phrase in case.answer_contains)
                   and all(phrase.casefold() not in response.answer.casefold() for phrase in case.answer_not_contains)
                   if case.answer_contains or case.answer_contains_any or case.answer_not_contains else None),
        "abstention": (response.answer == FALLBACK and not response.sources) if case.abstain else None,
        "products": len(response.products) >= case.min_products if case.min_products else None,
        "exact_facts": exact_facts(case, response, db),
        "stock_facts": stock_facts(case, response, db),
        "description_join": (all(
            any(source.source_id == product.description_source_id
                and source.url == "https://sardarandco.com/products/" + product.handle
                for source in response.sources)
            for product in response.products if product.description_source_id
        ) and len(response.sources) >= case.min_citations) if response.products or case.min_citations else None,
        "price_filter": (bool(response.products) and all(Decimal(product.price) < case.price_under
                         for product in response.products)) if case.price_under is not None else None,
    }
    if case.answer_contains_any:
        checks["answer"] &= any(phrase.casefold() in response.answer.casefold() for phrase in case.answer_contains_any)
    return checks


async def evaluate(case: ChatCase, model: ChatModel, sessions=SessionLocal) -> dict:
    if case.control:
        original = Case.model_validate(case.model_dump(include=set(Case.model_fields)))
        row = await evaluate_control(original, model)
        row["category"] = case.category
        # Controls exercise authorization/evidence with disposable SQL, not live retrieval.
        row["checks"] = {"isolated_trust_control": row["passed"]}
        return row
    started = perf_counter()
    observation = Observation()
    row = {"id": case.id, "category": case.category, "mode": "live_service", "role": case.role,
           "question": case.question}
    try:
        with sessions() as db:
            if db.get_bind().dialect.name == "postgresql":
                db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            # A trusted local evaluation actor; no account/session is inserted.
            user = User(role=case.role, is_active=True)
            with observe(model) as observation:
                response = await within_answer_deadline(_answer_chat(ChatRequest(message=case.question), user, db))
            checks = check_response(case, response, observation, db)
            row.update(checks=checks, response=response.model_dump(mode="json"))
    except (HTTPException, httpx.HTTPError, ModelError, SQLAlchemyError, ValueError, TimeoutError) as exc:
        row.update(checks={"service": False}, error_type=type(exc).__name__)
    row.update(observation=asdict(observation), total_ms=round((perf_counter() - started) * 1000, 1))
    row["failures"] = [name for name, passed in row["checks"].items() if passed is False]
    row["passed"] = not row["failures"]
    return row


def summarize(rows: list[dict]) -> dict:
    live = [row for row in rows if row["mode"] == "live_service"]
    latencies = sorted(row["total_ms"] for row in live)
    layers = sorted({name for row in rows for name in row["checks"]})
    calls = [call for row in live for call in row["observation"]["model_calls"]]
    return {
        "cases": len(rows), "passed": sum(row["passed"] for row in rows),
        "by_mode": {mode: {"cases": sum(row["mode"] == mode for row in rows),
                           "passed": sum(row["mode"] == mode and row["passed"] for row in rows)}
                    for mode in sorted({row["mode"] for row in rows})},
        "checks": {name: {"measured": sum(row["checks"].get(name) is not None for row in rows),
                          "passed": sum(row["checks"].get(name) is True for row in rows)} for name in layers},
        "live_latency_median_ms": median(latencies) if latencies else None,
        "live_latency_p95_ms": latencies[math.ceil(len(latencies) * .95) - 1] if latencies else None,
        "by_route_latency_ms": {route: {
            "cases": len(values := sorted(row["total_ms"] for row in live if row.get("response", {}).get("route") == route)),
            "median": median(values), "p95": values[math.ceil(len(values) * .95) - 1],
        } for route in sorted({row["response"]["route"] for row in live if "response" in row})},
        "model_calls": len(calls),
        "model_prompt_tokens_recorded": sum(call["prompt_tokens"] for call in calls
                                            if call.get("prompt_tokens") is not None),
        "model_output_tokens_recorded": sum(call["output_tokens"] for call in calls
                                            if call.get("output_tokens") is not None),
        "model_calls_without_token_counts": sum(call.get("prompt_tokens") is None or call.get("output_tokens") is None
                                               for call in calls),
        "web_search_calls": sum(row["name"] == "search_web" for case in live for row in case["observation"].get("tools", [])),
        "web_search_successes": sum(row["name"] == "search_web" and row["ok"] for case in live
                                    for row in case["observation"].get("tools", [])),
        "model_requested_web_search": sum("search_web" in call.get("requested_tools", []) for call in calls),
        "max_model_context_characters": max((call["context_characters"] for call in calls), default=None),
    }


def data_fingerprint() -> str:
    """Hash source authorization and product facts, without retaining their values."""
    digest = sha256()
    with SessionLocal() as db:
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        sources = db.execute(select(
            SourceRegistration.source_id, SourceRegistration.content_sha256,
            SourceRegistration.visibility, SourceRegistration.is_active,
            SourceRegistration.index_status, SourceRegistration.index_generation,
        ).order_by(SourceRegistration.source_id))
        for row in sources:
            digest.update(json.dumps(tuple(row), default=str, separators=(",", ":")).encode())
            digest.update(b"\n")
        products = db.execute(select(
            Product.id, Product.source_file_sha256, Product.source_row_number,
            Product.visibility, Product.status, Product.variant_sku, Product.variant_price,
            Product.variant_inventory_qty, Product.snapshot_currency,
        ).order_by(Product.id))
        for row in products:
            digest.update(json.dumps(tuple(row), default=str, separators=(",", ":")).encode())
            digest.update(b"\n")
    return digest.hexdigest()


def git_state() -> tuple[str, bool | None]:
    """Container images may omit Git; accept explicit build-context metadata."""
    try:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip())
        return revision, dirty
    except (FileNotFoundError, subprocess.CalledProcessError):
        return os.getenv("E6_GIT_REVISION", "unknown"), None


async def run(args: argparse.Namespace) -> None:
    cases = load_cases(args.cases)
    selected = getattr(args, "only", None)
    if selected:
        ids = set(selected.split(","))
        if not ids or ids - {case.id for case in cases}:
            raise ValueError("Unknown or empty selected case ID")
        cases = [case for case in cases if case.id in ids]
    settings = Settings()
    revision, dirty = git_state()
    # Reserve the report before expensive work; never overwrite earlier evidence.
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x", encoding="utf-8") as stream:
        metadata = {
            "schema_version": 1, "protocol_version": 3, "started_at": datetime.now(timezone.utc).isoformat(),
            "complete": False, "selected_case_ids": [case.id for case in cases],
            "case_sha256": sha256(args.cases.read_bytes()).hexdigest(),
            "git_revision": revision,
            "git_dirty": dirty,
            "evaluator_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
            "chat_model": settings.prototype_chat_model if args.current_model_first else settings.ollama_model,
            "embedding_model": MODEL, "collection": COLLECTION,
            "answer_timeout_seconds": settings.answer_timeout_seconds,
            "data_fingerprint_before": data_fingerprint(),
            "scope": "Read-only answer services; trusted local role; excludes HTTP auth, history, SSE and UI",
            "thresholds": "Every declared case check must pass; quality/latency business targets remain unset",
        }
        model = (OllamaChatModel(settings.model_copy(update={"ollama_model": settings.prototype_chat_model}),
                                 output_limit=160, tool_output_limit=96)
                 if args.current_model_first else OllamaChatModel(settings))
        rows = []

        def checkpoint() -> None:
            stream.seek(0)
            snapshot_summary = summarize(rows)
            if metadata["complete"]:
                snapshot_summary["data_stable_during_run"] = (
                    metadata["data_fingerprint_before"] == metadata["data_fingerprint_after"]
                )
            json.dump({"metadata": metadata, "case_definitions": [case.model_dump() for case in cases],
                       "summary": snapshot_summary, "cases": rows}, stream, indent=2)
            stream.write("\n")
            stream.truncate()
            stream.flush()
            os.fsync(stream.fileno())

        checkpoint()
        for case in cases:
            row = await evaluate(case, model)
            rows.append(row)
            print(f"{'PASS' if row['passed'] else 'FAIL'} [{row['mode']}] {case.id}: {row['total_ms']:.1f} ms {row['failures']}", flush=True)
            checkpoint()
        summary = summarize(rows)
        metadata["data_fingerprint_after"] = data_fingerprint()
        summary["data_stable_during_run"] = metadata["data_fingerprint_before"] == metadata["data_fingerprint_after"]
        metadata["complete"] = True
        checkpoint()
    print(json.dumps(summary, indent=2))
    if summary["passed"] != summary["cases"] or not summary["data_stable_during_run"]:
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument("--report", type=Path, required=True, help="New local JSON report; never overwritten")
    parser.add_argument("--current-model-first", action="store_true",
                        help="Use the prototype chat model and generation bounds used by /chat")
    parser.add_argument("--only", help="Comma-separated case IDs for a diagnostic subset")
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
