"""Serial E4 measurements on existing data; never imports or reindexes sources.

Run in the local Compose network with /app/app mounted from this working tree.
Reports contain internal answers/source identities and belong in data/extracted.
"""

import argparse
import asyncio
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

from sqlalchemy import select

from app.core.config import Settings
from app.db.models import SourceRegistration
from app.db.session import SessionLocal
from app.evaluation import run_chat, run_coverage
from app.evaluation.e4_inventory import inventory
from app.evaluation.fingerprint_collection import fingerprint
from app.evaluation.run_seed import check_result
from app.llm.ollama import OllamaChatModel
from app.rag.answer_seed import _approved_excerpts, _faq_answer, _matching_sentences, answer_from_points
from app.retrieval.authorization import ALLOWED_VISIBILITIES, authorized_points
from app.retrieval.search_seed import _query, search_for_role
from app.retrieval.selection import select_authorized_points
from app.services import company_answer

CASES_PATH = Path(__file__).with_name("e4_cases.json")


def diagnose(row: dict, stages: list[dict]) -> list[str]:
    """Report observed failing boundaries; this is not a semantic quality judge."""
    failures = row.get("failures", [])
    if not failures:
        return []
    if "service" in failures:
        return ["service"]
    if "routing" in failures:
        return ["routing"]
    if "retrieval" in failures:
        return ["retrieval"]
    if "citations" in failures:
        return ["citation_provenance"]
    if "expected_source" in failures and "answer" not in failures:
        return ["citation_identity_review"]
    if stages and not any(s["matching_sentences"] or s["exact_faq_answer"] for s in stages):
        return ["evidence_selection"]
    return ["answer_generation_or_support_review"]


def make_search(excluded: list[str]):
    def search(question: str, role: str) -> list[dict]:
        if not excluded:
            return search_for_role(question, role)
        allowed = ALLOWED_VISIBILITIES.get(role)
        if not allowed:
            return []
        # Exclude before Qdrant's top-32 budget, not by discarding returned hits.
        return _query(question, [
            {"key": "review_status", "match": {"value": "approved"}},
            {"key": "prototype_only", "match": {"value": False}},
            {"must_not": [{"key": "source_id", "match": {"any": excluded}}]},
        ], allowed)
    return search


async def chat_case(case, model, search) -> dict:
    stages = []

    def select_points(db, role, question, candidates):
        authorized = authorized_points(db, role, candidates)
        selected = select_authorized_points(db, role, question, candidates)
        excerpts = _approved_excerpts(selected)
        stages.append({"authorized_pool": [{"source_id": p["payload"]["source_id"],
                                             "url": p["payload"]["url"]} for p in authorized],
                       "selected": [{"source_id": p["payload"]["source_id"],
                                     "url": p["payload"]["url"]} for p in selected],
                       "matching_sentences": len(_matching_sentences(question, excerpts)),
                       "exact_faq_answer": _faq_answer(question, excerpts) is not None})
        return selected

    with patch.object(company_answer, "search_for_role", search), \
         patch.object(company_answer, "select_authorized_points", select_points):
        row = await run_chat.evaluate(case, model)
    row["evidence_stages"] = stages
    row["diagnostic_layers"] = diagnose(row, stages)
    return row


async def seed_rows(model, search) -> list[dict]:
    """Same retained questions/assertions, explicitly adapted to staff visibility."""
    definitions = json.loads(Path(__file__).with_name("seed_cases.json").read_text())
    rows = []
    for number, case in enumerate(definitions, 1):
        started = perf_counter()
        # Two original synthetic source controls deliberately bypass live search.
        if "points" in case:
            points = case["points"]
        else:
            candidates = await asyncio.to_thread(search, case["question"], "staff")
            with SessionLocal() as db:
                points = select_authorized_points(db, "staff", case["question"], candidates)
        result = await answer_from_points(case["question"], points, model)
        failures = check_result(result, case["expected_source"], case["answer_contains"])
        rows.append({"id": f"seed_{number}", "question": case["question"],
                     "passed": not failures, "failures": failures, "answer": result.text,
                     "citations": [vars(s) for s in result.sources],
                     "total_ms": round((perf_counter() - started) * 1000, 1)})
        print(f"{'PASS' if not failures else 'FAIL'} seed_{number} {failures}", flush=True)
    return rows


async def run(args) -> None:
    settings = Settings()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    # Never overwrite a baseline; keep metadata even if a later service fails.
    with args.report.open("x", encoding="utf-8") as stream:
        metadata = {"started_at": datetime.now(timezone.utc).isoformat(), "suite": args.suite,
                    "model": settings.ollama_model, "answer_timeout_seconds": settings.answer_timeout_seconds,
                    "evaluator_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
                    "scope": "Read-only local role services; HTTP authentication/UI checked separately",
                    "comparison": "uploads excluded before ranking; not a historical pre-ingestion replay"
                                  if args.exclude_uploads else "current uploaded corpus",
                    "sql_before": run_chat.data_fingerprint(), "vectors_before": await fingerprint()}
        digest = sha256()
        for path in sorted(Path(__file__).resolve().parents[1].rglob("*.py")):
            digest.update(str(path.relative_to(Path(__file__).resolve().parents[1])).encode())
            digest.update(path.read_bytes())
        metadata["application_python_sha256"] = digest.hexdigest()
        json.dump({"metadata": metadata, "status": "running"}, stream)
        stream.flush()
        with SessionLocal() as db:
            excluded = list(db.scalars(select(SourceRegistration.source_id).where(
                SourceRegistration.source_type.in_(["text", "pdf", "markdown"])))) if args.exclude_uploads else []
        metadata["excluded_source_ids"] = excluded
        search = make_search(excluded)
        model = OllamaChatModel(settings)
        rows, definitions, summary = [], [], {}
        if args.suite == "inventory":
            details = await asyncio.to_thread(inventory, settings)
            summary = {k: v for k, v in details.items() if k != "sources"}
        elif args.suite in {"e4", "chat"}:
            path = CASES_PATH if args.suite == "e4" else run_chat.CASES_PATH
            cases = run_chat.load_cases(path)
            definitions = [c.model_dump() for c in cases]
            metadata["case_sha256"] = sha256(path.read_bytes()).hexdigest()
            for case in cases:
                row = await chat_case(case, model, search)
                rows.append(row)
                print(f"{'PASS' if row['passed'] else 'FAIL'} {case.id}: {row['total_ms']} ms {row['failures']}", flush=True)
            summary = run_chat.summarize(rows)
        elif args.suite == "full-site":
            path = Path(__file__).with_name("full_site_cases.json")
            cases = run_coverage.load_cases(path)
            definitions = [c.model_dump() for c in cases]
            metadata["case_sha256"] = sha256(path.read_bytes()).hexdigest()
            for case in cases:
                row = await run_coverage.evaluate(case, model, search=search)
                rows.append(row)
                print(f"{'PASS' if row['passed'] else 'FAIL'} {case.id}: {row['total_ms']} ms {row['failures']}", flush=True)
            summary = run_coverage.summarize(rows)
        else:
            path = Path(__file__).with_name("seed_cases.json")
            definitions = json.loads(path.read_text())
            metadata["case_sha256"] = sha256(path.read_bytes()).hexdigest()
            rows = await seed_rows(model, search)
            summary = {"cases": len(rows), "passed": sum(row["passed"] for row in rows),
                       "scope": "retained seed assertions with staff-role search; original CLI is public-only"}
        metadata.update(sql_after=run_chat.data_fingerprint(), vectors_after=await fingerprint())
        summary["data_stable"] = (metadata["sql_before"] == metadata["sql_after"]
                                  and metadata["vectors_before"] == metadata["vectors_after"])
        stream.seek(0)
        json.dump({"metadata": metadata, "summary": summary, "case_definitions": definitions,
                   "cases": rows, **({"inventory": details} if args.suite == "inventory" else {})}, stream, indent=2)
        stream.truncate()
        stream.write("\n")
    print(json.dumps(summary, indent=2))
    if (not summary["data_stable"] or summary.get("integrity_failures")
        or summary.get("orphan_point_count") or summary.get("registry_rejected_point_count")
        or summary.get("passed", 0) != summary.get("cases", 0)):
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=["inventory", "e4", "chat", "full-site", "seed"], default="e4")
    parser.add_argument("--exclude-uploads", action="store_true")
    parser.add_argument("--report", type=Path, required=True)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
