"""Run a small live RAG baseline against local Ollama and Qdrant.

Run from the project root:
    PYTHONPATH=backend backend/.venv/bin/python -m app.evaluation.run_seed
"""

import asyncio
import json
from pathlib import Path

from app.core.config import Settings
from app.db.session import SessionLocal
from app.llm.ollama import OllamaChatModel
from app.rag.answer_seed import CitedAnswer, FALLBACK, answer_from_points
from app.retrieval.search_seed import search_approved
from app.retrieval.selection import select_authorized_points


CASES_PATH = Path(__file__).with_name("seed_cases.json")


def check_result(result: CitedAnswer, expected_source: str | None, phrases: list[str]) -> list[str]:
    """Check abstention, citation, and minimal answer content separately."""
    if expected_source is None:
        return [] if result.text == FALLBACK and not result.sources else [
            "expected an uncited abstention"
        ]

    failures: list[str] = []
    if result.text == FALLBACK:
        failures.append("expected an answer")
    if expected_source not in (source.url for source in result.sources):
        failures.append("expected source is missing")
    for phrase in phrases:
        if phrase.casefold() not in result.text.casefold():
            failures.append(f"answer is missing {phrase!r}")
    return failures


async def main() -> None:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    model = OllamaChatModel(Settings())
    passed = 0

    for number, case in enumerate(cases, start=1):
        question = case["question"]
        # Synthetic points exercise unsafe source text without putting it in Qdrant.
        points = case.get("points")
        if points is None:
            points = await asyncio.to_thread(search_approved, question)
            with SessionLocal() as db:
                points = select_authorized_points(db, "staff", question, points)
        result = await answer_from_points(question, points, model)
        failures = check_result(result, case["expected_source"], case["answer_contains"])
        print(f"{number}. {'PASS' if not failures else 'FAIL'}: {question}")
        print(f"   Answer: {result.text}")
        print(f"   Sources: {', '.join(source.url for source in result.sources) or '(none)'}")
        for failure in failures:
            print(f"   Reason: {failure}")
        passed += not failures

    print(f"\n{passed}/{len(cases)} cases passed")
    if passed != len(cases):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
