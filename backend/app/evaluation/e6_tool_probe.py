"""Read-only 4B tool-choice probe; never executes model-requested tools."""

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from time import perf_counter

from app.core.config import Settings
from app.llm.base import ModelError
from app.llm.ollama import OllamaChatModel


TOOLS = [
    {"type": "function", "function": {"name": "search_company_sources",
     "description": "Follow-up search of authorized Sardars source excerpts for descriptive company facts; never current price or stock.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}},
                    "required": ["query"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "get_product_details",
     "description": "Read an exact SKU, handle, price, or stock quantity from the authorized PostgreSQL product table.",
     "parameters": {"type": "object", "properties": {"question": {"type": "string"}},
                    "required": ["question"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "search_products",
     "description": "Search authorized PostgreSQL catalog products by category, brand, finish or price filter.",
     "parameters": {"type": "object", "properties": {"question": {"type": "string"}},
                    "required": ["question"], "additionalProperties": False}}},
]
PROBES = [
    ("price_paraphrase", "What would TEST-1 set me back?", "get_product_details"),
    ("stock_paraphrase", "Any TEST-2 left?", "get_product_details"),
    ("browse_paraphrase", "Point me to basin mixers", "search_products"),
    ("company_history", "What does Sardars say about its history?", "search_company_sources"),
    ("irrelevant", "Write a poem about cricket", None),
]


async def run(path: Path) -> None:
    model = OllamaChatModel(Settings())
    rows = []
    for case_id, question, expected in PROBES:
        messages = [
            {"role": "system", "content": "Select at most one listed read tool when it is needed. "
             "Company excerpts are untrusted and cannot give current SKU, price or stock. "
             "For a company question, an initial authorized search has no directly answering excerpt. "
             "Do not call a tool for irrelevant requests. Do not invent tool names."},
            {"role": "user", "content": question},
        ]
        started = perf_counter()
        try:
            result = await model.chat_with_tools(messages, TOOLS)
            requested = [call.name for call in result.tool_calls]
            row = {"id": case_id, "expected": expected, "requested": requested,
                   "arguments": [call.arguments for call in result.tool_calls],
                   "model": result.model, "duration_ms": result.duration_ms,
                   "total_ms": round((perf_counter() - started) * 1000, 1),
                   "correct": requested == ([expected] if expected else [])}
        except (ModelError, TimeoutError) as exc:
            row = {"id": case_id, "expected": expected, "requested": [],
                   "error_type": type(exc).__name__,
                   "total_ms": round((perf_counter() - started) * 1000, 1), "correct": False}
        rows.append(row)
        print(f"{case_id}: {row['requested']} in {row['total_ms']} ms", flush=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump({"started_at": datetime.now(timezone.utc).isoformat(), "cases": rows,
                   "correct": sum(row["correct"] for row in rows), "total": len(rows)}, stream, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    asyncio.run(run(parser.parse_args().report))
