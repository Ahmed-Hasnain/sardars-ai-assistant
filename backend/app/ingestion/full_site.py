"""Prepare, inspect and resume serial batches from the full saved website crawl.

Default is offline status/preparation. --apply runs at most --max-batches jobs.
The local ledger references durable PostgreSQL jobs; it is not a work queue.
"""

import argparse
from collections import Counter, deque
from contextlib import contextmanager
import fcntl
from hashlib import sha256
import json
from pathlib import Path
import time
from uuid import uuid4

import httpx
from sqlalchemy.exc import SQLAlchemyError

from app.ingestion.chunking import chunk_record
from app.ingestion.coverage import load_all
from app.ingestion.descriptive_site import METHOD, descriptive_document
from app.ingestion.job_requests import JobRequest
from app.ingestion.job_runner import JobFailed, run_job
from app.ingestion.job_store import enqueue, job_view
from app.ingestion.site_index import WebsiteIndexer

DEFAULT_STATE = Path("data/extracted/full_site_descriptive")
MAX_STATE_BYTES = 32 * 1024 * 1024
MAX_SOURCE_CHUNKS = 64


def digest(path: Path) -> str:
    if not path.is_file() or path.stat().st_size > MAX_STATE_BYTES:
        raise ValueError("Expected a bounded saved file")
    return sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict:
    digest(path)
    try:
        value = json.loads(path.read_bytes())
    except (ValueError, RecursionError) as exc:
        raise ValueError("Invalid local import state") from exc
    if not isinstance(value, dict):
        raise ValueError("Expected an import state object")
    return value


def save_json(path: Path, value: dict) -> None:
    """Atomic replacement: an interruption leaves the previous ledger readable."""
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
        stream.flush()
        import os
        os.fsync(stream.fileno())
    temporary.replace(path)


@contextmanager
def state_lock(state: Path):
    with (state / "runner.lock").open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("Another runner owns this import state") from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def prepare(input_path: Path, state: Path, *, batch_sources: int = 5, batch_chunks: int = 24) -> dict:
    if not 1 <= batch_sources <= 10 or not 1 <= batch_chunks <= MAX_SOURCE_CHUNKS:
        raise ValueError("Batch limits: 1–10 sources and 1–64 target chunks")
    originals = load_all(input_path)
    original_digest = digest(input_path)
    documents, records, batches, current = [], [], [], []
    for original in originals:
        document, record = descriptive_document(original)
        if document:
            count = len(chunk_record(document.model_dump(mode="json")))
            if count > MAX_SOURCE_CHUNKS:
                document = None
                record.update(status="rejected", reason="source_exceeds_hard_chunk_limit")
            else:
                record["chunks"] = count
                documents.append(document)
        records.append(record)
    # Start with small examples of every content type, then cover the rest.
    # Sorting changes scheduling only; it never truncates a source's text.
    groups = [deque(sorted((doc for doc in documents if doc.source_type == kind),
                           key=lambda doc: (len(doc.text.split()), doc.url)))
              for kind in ("pages", "articles", "products")]
    ordered = []
    while any(groups):
        for group in groups:
            if group:
                ordered.append(group.popleft())
    current_chunks = 0
    for document in ordered:
        count = len(chunk_record(document.model_dump(mode="json")))
        if current and (len(current) >= batch_sources or current_chunks + count > batch_chunks):
            batches.append(current)
            current, current_chunks = [], 0
        current.append(document.source_id)
        current_chunks += count
    if current:
        batches.append(current)
    state.mkdir(parents=True, exist_ok=False)
    with state_lock(state):
        path = state / "documents.jsonl"
        path.write_text("".join(document.model_dump_json() + "\n" for document in documents), encoding="utf-8")
        plan = {"version": 1, "method": METHOD, "input_path": str(input_path.resolve()),
                "input_sha256": original_digest, "documents_sha256": digest(path),
                "batch_sources": batch_sources, "batch_chunks": batch_chunks,
                "max_source_chunks": MAX_SOURCE_CHUNKS, "sources": records, "batches": batches}
        save_json(state / "plan.json", plan)
        save_json(state / "ledger.json", {"plan_sha256": digest(state / "plan.json"),
                  "sources": {row["source_id"]: row["status"] for row in records},
                  "batches": [{"status": "pending", "job_id": None, "history": []} for _ in batches]})
    return summary(state)


def load_state(state: Path) -> tuple[dict, dict, dict]:
    plan, ledger = read_json(state / "plan.json"), read_json(state / "ledger.json")
    if (plan.get("version") != 1 or plan.get("method") != METHOD
        or ledger.get("plan_sha256") != digest(state / "plan.json")
        or plan.get("documents_sha256") != digest(state / "documents.jsonl")):
        raise ValueError("Import plan/prepared snapshot changed; prepare a new state directory")
    # Original snapshot is required for reproducible provenance, even on resume.
    if plan.get("input_sha256") != digest(Path(plan["input_path"])):
        raise ValueError("Original crawl changed; retain this snapshot and prepare new state")
    documents = {doc.source_id: doc for doc in load_all(state / "documents.jsonl")}
    records = {row["source_id"]: row for row in plan["sources"]}
    selected = [identity for batch in plan["batches"] for identity in batch]
    if (len(selected) != len(set(selected)) or set(selected) != set(documents)
        or set(ledger["sources"]) != set(records) or len(ledger["batches"]) != len(plan["batches"])):
        raise ValueError("Import ledger does not match the prepared plan")
    for batch in plan["batches"]:
        request = JobRequest(operation="import", documents=[documents[identity] for identity in batch])
        request.snapshot()
    return plan, ledger, documents


def summary(state: Path) -> dict:
    plan, ledger, _ = load_state(state)
    ready = {identity for identity, status in ledger["sources"].items() if status in {"imported", "skipped"}}
    return {"state": str(state), "method": METHOD, "crawl_documents": len(plan["sources"]),
            "eligible_documents": sum(row["status"] != "rejected" for row in plan["sources"]),
            "derived_documents": sum(row.get("derived", False) for row in plan["sources"] if row["status"] != "rejected"),
            "source_statuses": dict(Counter(ledger["sources"].values())),
            "rejection_reasons": dict(Counter(row["reason"] for row in plan["sources"] if row["status"] == "rejected")),
            "planned_chunks": sum(row.get("chunks", 0) for row in plan["sources"] if row["status"] != "rejected"),
            "completed_documents": len(ready),
            "completed_chunks": sum(row.get("chunks", 0) for row in plan["sources"] if row["source_id"] in ready),
            "batches": dict(Counter(batch["status"] for batch in ledger["batches"]))}


def apply(state: Path, sessions, settings, client: httpx.Client, *, max_batches: int = 1,
          retry_failed: bool = False, verify: bool = False) -> dict:
    """One serial operator, fresh deadline per job, stop on the first failure."""
    from app.db.models import IngestionJob

    if not 1 <= max_batches <= 1000:
        raise ValueError("Run between one and 1000 serial batches")
    with state_lock(state):
        plan, ledger, documents = load_state(state)
        executed = 0
        for index, identities in enumerate(plan["batches"]):
            batch = ledger["batches"][index]
            if batch["status"] == "completed" and not verify:
                continue
            if executed >= max_batches:
                break
            if batch["status"] == "failed" and not retry_failed:
                raise ValueError("Failed batch requires --retry-failed after inspecting its job")
            request = JobRequest(operation="import", documents=[documents[identity] for identity in identities])
            if batch["status"] == "completed":
                batch["history"].append({"job_id": batch["job_id"], "result": batch.get("result")})
                batch["job_id"] = None
            if batch["job_id"] is None:
                batch["job_id"] = str(uuid4())
                batch["status"] = "pending"
            # Persist the identity BEFORE admission to PostgreSQL. Admission is
            # idempotent for this exact snapshot, closing the crash window.
            save_json(state / "ledger.json", ledger)
            enqueue(sessions, request, job_id=batch["job_id"])
            with sessions() as db:
                view = job_view(db.get(IngestionJob, batch["job_id"]))
            if view["status"] == "completed":
                result = {**view["result"], "job_id": view["job_id"], "attempts": view["attempts"]}
            else:
                if view["status"] != "pending" and (not retry_failed or (view["status"] == "processing" and not view["lease_expired"])):
                    raise ValueError("Stored job needs explicit retry after failure/lease expiry")
                batch["status"] = "processing"
                for identity in identities:
                    ledger["sources"][identity] = "processing"
                save_json(state / "ledger.json", ledger)
                started = time.monotonic()
                print(json.dumps({"batch": index + 1, "total_batches": len(plan["batches"]),
                                  "status": "processing", "job_id": batch["job_id"],
                                  "sources": len(identities), "chunks": sum(len(chunk_record(documents[identity].model_dump(mode="json"))) for identity in identities)}), flush=True)
                try:
                    result = run_job(sessions, batch["job_id"], WebsiteIndexer(settings, client), retry=view["status"] != "pending")
                except (JobFailed, KeyboardInterrupt):
                    batch["status"] = "failed"
                    for identity in identities:
                        ledger["sources"][identity] = "failed"
                    save_json(state / "ledger.json", ledger)
                    raise
                result["duration_seconds"] = round(time.monotonic() - started, 2)
            batch.update(status="completed", result=result)
            for row in result["sources"]:
                ledger["sources"][row["source_id"]] = "skipped" if row["index_action"] == "skipped" else "imported"
            save_json(state / "ledger.json", ledger)
            executed += 1
            print(json.dumps({"batch": index + 1, "status": "completed", "job_id": batch["job_id"],
                              "indexed_chunks": result["indexed_chunks"], "skipped_sources": result["skipped_sources"],
                              "duration_seconds": result.get("duration_seconds")}), flush=True)
    return summary(state)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/extracted/public_site_full.jsonl"))
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--prepare", action="store_true", help="Create a NEW offline plan and ledger")
    parser.add_argument("--batch-sources", type=int, default=5)
    parser.add_argument("--batch-chunks", type=int, default=24, help="Target; a longer source gets its own job (hard cap 64)")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--max-batches", type=int, default=1)
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--verify", action="store_true", help="Recheck completed batches using the lifecycle importer")
    args = parser.parse_args(argv)
    if args.prepare and args.apply or (args.retry_failed or args.verify) and not args.apply:
        parser.error("Prepare is offline; retry/verify require --apply")
    try:
        if args.prepare:
            result = prepare(args.input, args.state, batch_sources=args.batch_sources, batch_chunks=args.batch_chunks)
        elif args.apply:
            from app.core.config import Settings
            from app.db.session import SessionLocal
            with httpx.Client(follow_redirects=False) as client:
                # Keep ONE model warm between serial requests; no concurrency.
                settings = Settings().model_copy(update={"ollama_keep_alive": 120})
                result = apply(args.state, SessionLocal, settings, client, max_batches=args.max_batches,
                               retry_failed=args.retry_failed, verify=args.verify)
        else:
            result = summary(args.state)
    except SQLAlchemyError:
        parser.error("Database unavailable; inspect the saved ledger/jobs before resuming")
    except JobFailed as exc:
        parser.error(f"Batch failed; job_id={exc.job_id}: {exc}; inspect and use --retry-failed")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # Never print Pydantic errors, raw snapshots, or service bodies.
        message = str(exc) if type(exc) is ValueError else "Invalid or unavailable local import state/configuration"
        parser.error(message)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
