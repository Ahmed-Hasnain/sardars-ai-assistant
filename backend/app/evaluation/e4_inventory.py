"""Read-only inventory of the actual E4 registry, durable jobs and vector payloads."""

from collections import Counter, defaultdict
from hashlib import sha256
import math
from statistics import median

import httpx
from sqlalchemy import select, text

from app.core.config import Settings
from app.db.models import IngestionJob, SourceRegistration
from app.db.session import SessionLocal
from app.ingestion.chunking import chunk_record
from app.ingestion.extraction import storage_path
from app.rag.answer_seed import FAQ_PAIR, _approved_excerpts, _faq_answer
from app.rag.answer_seed import CHANGING_FACT_PATTERN, MAX_SENTENCE_CHARS
from app.rag.claim_safety import UNVERIFIED_BUSINESS_FACT, unsafe_descriptive_claim
from app.rag.text_safety import contains_prompt_instruction
from app.retrieval.authorization import authorized_points
from app.retrieval.seed_config import COLLECTION


def distribution(values) -> dict:
    values = sorted(values)
    return {"count": len(values), "median": median(values) if values else None,
            "p95": values[math.ceil(len(values) * .95) - 1] if values else None}


def scan_points(settings: Settings) -> list[dict]:
    points, offset = [], None
    with httpx.Client(timeout=30) as client:
        while True:
            body = {"limit": 256, "with_payload": True, "with_vector": False}
            if offset is not None:
                body["offset"] = offset
            response = client.post(
                f"{settings.qdrant_base_url.rstrip('/')}/collections/{COLLECTION}/points/scroll",
                json=body,
            )
            response.raise_for_status()
            result = response.json()["result"]
            batch = result["points"]
            if not isinstance(batch, list) or len(batch) > 256:
                raise ValueError("Invalid inventory scroll response")
            points.extend(batch)
            if len(points) > 100_000:
                raise ValueError("Inventory point limit exceeded")
            next_offset = result.get("next_page_offset")
            if next_offset is None:
                return points
            if next_offset == offset or not batch:
                raise ValueError("Inventory scroll did not advance")
            offset = next_offset


def faq_audit(document: dict, points: list[dict]) -> dict | None:
    """Compare complete snapshot answers with what the FAQ extractor can see.

    This is an offline upper bound; it does not measure ranking or chat routing.
    """
    pairs = list(FAQ_PAIR.finditer(document["text"]))
    if not pairs:
        return None
    if len(pairs) > 1000:
        raise ValueError("FAQ audit pair limit exceeded")
    excerpts = [e for p in points for e in _approved_excerpts([p])]
    eligible, reachable, indexed, partial = 0, 0, 0, []
    for pair in pairs:
        full = " ".join(pair["answer"].split())
        safe = (10 <= len(full) <= MAX_SENTENCE_CHARS and not unsafe_descriptive_claim(full)
                and not contains_prompt_instruction(full))
        eligible += safe
        reachable += bool(safe and not CHANGING_FACT_PATTERN.search(pair["question"])
                          and not UNVERIFIED_BUSINESS_FACT.search(pair["question"]))
        answers = {result.text.removesuffix(" [1]") for excerpt in excerpts
                   if (result := _faq_answer(pair["question"], [excerpt])) is not None}
        indexed += bool(answers)
        if any(answer != full for answer in answers):
            partial.append(pair["question"])
    return {"pairs": len(pairs), "full_answer_guard_eligible": eligible,
            "question_and_answer_guard_eligible": reachable,
            "indexed_answer_candidates": indexed, "partial_answer_questions": partial}


def inventory(settings: Settings) -> dict:
    points = scan_points(settings)
    grouped = defaultdict(list)
    for point in points:
        grouped[point["payload"].get("source_id")].append(point)
    with SessionLocal() as db:
        db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        sources = db.scalars(select(SourceRegistration).order_by(SourceRegistration.source_id)).all()
        jobs = db.scalars(select(IngestionJob).order_by(IngestionJob.created_at)).all()
        job_map = {job.id: job for job in jobs}
        roles = {}
        for role in ("admin", "staff", "unknown"):
            allowed = []
            for offset in range(0, len(points), 256):
                allowed.extend(authorized_points(db, role, points[offset:offset + 256]))
            roles[role] = {"points": len(allowed),
                           "sources": len({p["payload"]["source_id"] for p in allowed})}
        rows = []
        for source in sources:
            batch = grouped.get(source.source_id, [])
            job = job_map.get(source.index_job_id)
            document = next((d for d in (job.request.get("documents", []) if job else [])
                             if d.get("source_id") == source.source_id), None)
            expected = chunk_record(document) if document else None
            actual = sorted((p["payload"].get("chunk_index"), p["payload"].get("text")) for p in batch)
            expected_text = [(c["chunk_index"], c["text"]) for c in expected] if expected else None
            original_ok = None
            if source.storage_key:
                path = storage_path(settings, source.storage_key)
                if path.exists() and path.stat().st_size <= 5 * 1024 * 1024:
                    original_ok = sha256(path.read_bytes()).hexdigest() == source.file_sha256
                else:
                    original_ok = False
            rows.append({"source_id": source.source_id, "url": source.url, "title": source.title,
                         "type": source.source_type, "visibility": source.visibility,
                         "active": source.is_active, "status": source.index_status,
                         "generation": source.index_generation, "checksum": source.content_sha256,
                         "fetched_at": str(source.fetched_at), "points": len(batch),
                         "original_checksum_ok": original_ok,
                         "snapshot_chunks_match": actual == expected_text if expected_text is not None else None,
                         "snapshot_checksum_ok": (sha256(document["text"].encode()).hexdigest()
                                                  == source.content_sha256) if document else None,
                         "faq_audit": faq_audit(document, batch) if document else None})
        failed = Counter((j.error_code, j.error_message) for j in jobs if j.status == "failed")
        crawls = []
        for job in jobs:
            if job.operation != "crawl":
                continue
            children = [j for j in jobs if j.parent_job_id == job.id]
            last_finished = max((j.finished_at for j in children if j.finished_at), default=None)
            crawls.append({"id": job.id, "status": job.status, "attempts": job.attempts,
                           "discovered": (job.result or {}).get("discovered_pages"),
                           "children": dict(Counter(j.status for j in children)),
                           "wall_seconds": (last_finished - job.created_at).total_seconds()
                                           if last_finished else None})
        completed = [j for j in jobs if j.status == "completed" and j.operation == "import"
                     and j.started_at and j.finished_at]
        return {"source_count": len(sources), "point_count": len(points),
                "source_types": dict(Counter(s.source_type for s in sources)),
                "source_visibility": dict(Counter(s.visibility for s in sources)),
                "job_count": len(jobs), "job_states": dict(Counter(j.status for j in jobs)),
                "failed_jobs": [{"code": code, "message": message, "count": count}
                                for (code, message), count in failed.items()],
                "import_execution_seconds": distribution((j.finished_at-j.started_at).total_seconds() for j in completed),
                "import_queue_seconds": distribution((j.started_at-j.created_at).total_seconds() for j in completed),
                "crawls": crawls, "roles": roles, "sources": rows,
                "orphan_point_count": sum(len(v) for k, v in grouped.items()
                                          if k not in {s.source_id for s in sources}),
                "registry_rejected_point_count": len(points) - roles["admin"]["points"],
                "integrity_failures": [row["source_id"] for row in rows
                                       if any(row[key] is False for key in (
                                           "snapshot_chunks_match", "snapshot_checksum_ok", "original_checksum_ok"))]}
