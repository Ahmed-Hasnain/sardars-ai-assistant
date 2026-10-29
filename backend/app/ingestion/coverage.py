"""Audit saved company content and import one explicit, checksum-pinned batch."""

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy.exc import SQLAlchemyError

from app.ingestion.chunking import chunk_record
from app.ingestion.job_requests import JobRequest
from app.ingestion.job_runner import JobFailed, run_job
from app.ingestion.job_store import enqueue
from app.ingestion.prepare_site import MAX_INPUT_BYTES, MAX_RECORD_BYTES, MAX_RECORDS, load_selected_documents
from app.ingestion.public_site import source_type
from app.ingestion.site_documents import WebsiteDocument
from app.rag.text_safety import contains_prompt_instruction

DEFAULT_MANIFEST = Path(__file__).resolve().parents[3] / "data/coverage/public_site_v1.json"
CHANGING_CLAIMS = re.compile(r"\b(?:prices?|pricing|stock|inventory|availability|discounts?|promotions?|sale|sold out)\b", re.I)
TRANSACTION_CLAIMS = re.compile(r"\b(?:refunds?|returns?|exchanges?|payment|delivery|shipping|warranty)\b", re.I)


class CoverageSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=2048)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    purpose: str = Field(min_length=1, max_length=300)

    @field_validator("url")
    @classmethod
    def descriptive_url(cls, value: str) -> str:
        if source_type(value) is None:
            raise ValueError("Select a descriptive owner-authorized Sardars URL")
        return value


class CoverageManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[a-z0-9_]{1,80}$")
    sources: list[CoverageSource] = Field(min_length=1, max_length=10)


def load_manifest(path: Path) -> CoverageManifest:
    with path.open("rb") as stream:
        raw = stream.read(16 * 1024 + 1)
    if len(raw) > 16 * 1024:
        raise ValueError("Coverage manifest exceeds its size limit")
    try:
        manifest = CoverageManifest.model_validate_json(raw)
    except ValidationError as exc:
        raise ValueError("Invalid coverage manifest") from exc
    if len({source.url for source in manifest.sources}) != len(manifest.sources):
        raise ValueError("Select each manifest URL only once")
    return manifest


def normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def flags(document: WebsiteDocument) -> list[str]:
    result = []
    if len(document.text.split()) < 20:
        result.append("short_content")
    paragraphs = [normalize(part) for part in re.split(r"\n\s*\n", document.text) if len(part.strip()) >= 20]
    if len(paragraphs) != len(set(paragraphs)):
        result.append("duplicate_paragraphs")
    if CHANGING_CLAIMS.search(document.text):
        result.append("changing_claims")
    if TRANSACTION_CLAIMS.search(document.text):
        result.append("transaction_or_policy_claims")
    if contains_prompt_instruction(document.title + "\n" + document.text):
        result.append("instruction_patterns")
    if re.search(r"Applicable Water Pressure.{0,30}\b\d[\d -]*\s*V\b", document.text, re.I):
        result.append("possibly_mislabeled_specification")
    return result


def audit(documents: list[WebsiteDocument]) -> dict:
    seen = {}
    counts = Counter()
    sources = []
    for document in documents:
        issues = flags(document)
        digest = sha256(normalize(document.text).encode()).hexdigest()
        if digest in seen:
            issues.append("duplicate_normalized_document")
        else:
            seen[digest] = document.url
        counts.update(issues)
        sources.append({"source_id": document.source_id, "url": document.url, "source_type": document.source_type,
                        "content_sha256": document.content_sha256, "fetched_at": document.fetched_at.isoformat(),
                        "words": len(document.text.split()), "chunks": len(chunk_record(document.model_dump(mode="json"))),
                        "flags": issues})
    return {"documents": len(documents), "source_types": dict(Counter(doc.source_type for doc in documents)),
            "flag_counts": dict(counts), "flagged_documents": sum(bool(source["flags"]) for source in sources),
            "sources": sources}


def load_all(path: Path) -> list[WebsiteDocument]:
    if not path.is_file() or path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("Input must be a bounded existing crawler JSONL file")
    rows = {}
    total = 0
    with path.open("rb") as stream:
        for line_number, line in enumerate(iter(lambda: stream.readline(MAX_RECORD_BYTES + 1), b""), 1):
            total += len(line)
            if line_number > MAX_RECORDS or len(line) > MAX_RECORD_BYTES or total > MAX_INPUT_BYTES:
                raise ValueError("Crawler input exceeds a processing limit")
            if not line.strip():
                continue
            try:
                document = WebsiteDocument.model_validate_json(line)
            except (ValueError, RecursionError) as exc:
                raise ValueError(f"Invalid crawler document at line {line_number}") from exc
            if document.url in rows and document != rows[document.url]:
                raise ValueError("Conflicting crawler records")
            rows[document.url] = document
    return list(rows.values())


def prepare(path: Path, manifest: CoverageManifest) -> tuple[list[WebsiteDocument], dict]:
    documents = load_selected_documents(path, [source.url for source in manifest.sources])
    expected = {source.url: source.content_sha256 for source in manifest.sources}
    if any(document.content_sha256 != expected[document.url] for document in documents):
        raise ValueError("Selected content changed; audit it and update the manifest/checks before import")
    report = audit(documents)
    if report["flagged_documents"]:
        raise ValueError("Selected batch contains quality/changing-fact flags; use --audit-all to inspect and select suitable descriptive sources")
    return documents, report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/extracted/public_site_full.jsonl"))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--audit-all", action="store_true", help="Audit the bounded extraction without indexing it")
    parser.add_argument("--apply", action="store_true", help="Import only the manifest batch after quality checks")
    parser.add_argument("--report", type=Path, help="Save a new JSON report; existing files are refused")
    args = parser.parse_args(argv)
    if args.audit_all and args.apply:
        parser.error("--audit-all never indexes sources")
    job_id = None
    result = {"phase": 5, "step": 5, "status": "audit"}
    try:
        if args.report and args.report.exists():
            raise ValueError("Report already exists; choose a new output file")
        if args.audit_all:
            result["audit"] = audit(load_all(args.input))
        else:
            manifest = load_manifest(args.manifest)
            documents, report = prepare(args.input, manifest)
            result.update(manifest=manifest.name, audit=report)
            if args.apply:
                from app.core.config import Settings
                from app.db.session import SessionLocal
                from app.ingestion.site_index import WebsiteIndexer
                job_id = enqueue(SessionLocal, JobRequest(operation="import", documents=documents))
                with httpx.Client(follow_redirects=False) as client:
                    result.update(run_job(SessionLocal, job_id, WebsiteIndexer(Settings(), client)))
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            with args.report.open("x", encoding="utf-8") as stream:
                json.dump(result, stream, indent=2)
                stream.write("\n")
    except SQLAlchemyError:
        parser.error("Database unavailable; inspect job status after recovery")
    except JobFailed as exc:
        parser.error(f"Coverage import failed; job_id={exc.job_id}: {exc}")
    except ValidationError:
        parser.error("Invalid local ingestion configuration")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    # Full source audit metadata stays in the optional local report.
    print(json.dumps({key: value for key, value in result.items() if key != "audit"} | {
        "audited_documents": result["audit"]["documents"], "source_types": result["audit"]["source_types"],
        "quality_flag_counts": result["audit"]["flag_counts"],
    }, indent=2))


if __name__ == "__main__":
    main()
