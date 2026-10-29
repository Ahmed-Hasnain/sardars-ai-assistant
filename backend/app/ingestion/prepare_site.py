"""Phase 5, Step 1: validate selected saved website records and prepare chunks.

This local CLI makes no network requests or database/index changes. It does not
authorize sources. Only explicitly selected records are document-validated.
"""

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from app.ingestion.chunking import MAX_WORDS, OVERLAP_WORDS, chunk_record
from app.ingestion.public_site import source_type
from app.ingestion.site_documents import WebsiteDocument
from app.ingestion.documents import SuppliedDocument


MAX_INPUT_BYTES = 32 * 1024 * 1024
MAX_RECORD_BYTES = 256 * 1024
MAX_RECORDS = 5_000
MAX_SELECTED_DOCUMENTS = 10


def load_selected_documents(path: Path, urls: list[str]) -> list[WebsiteDocument]:
    """Read a bounded JSONL extraction and fail on conflicting selected records."""
    if not 1 <= len(urls) <= MAX_SELECTED_DOCUMENTS:
        raise ValueError(f"Select between 1 and {MAX_SELECTED_DOCUMENTS} URLs")
    if len(set(urls)) != len(urls):
        raise ValueError("Select each URL only once")
    if any(len(url) > 2048 or source_type(url) is None for url in urls):
        raise ValueError("Select only supported descriptive Sardars HTTPS URLs")
    if not path.is_file():
        raise ValueError("Input must be an existing regular JSONL file")
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("Extraction file exceeds the input size limit")

    selected: dict[str, WebsiteDocument] = {}
    requested = set(urls)
    total_bytes = 0
    with path.open("rb") as stream:
        lines = iter(lambda: stream.readline(MAX_RECORD_BYTES + 1), b"")
        for line_number, line in enumerate(lines, start=1):
            total_bytes += len(line)
            if (
                line_number > MAX_RECORDS
                or len(line) > MAX_RECORD_BYTES
                or total_bytes > MAX_INPUT_BYTES
            ):
                raise ValueError(f"Extraction exceeds a processing limit at line {line_number}")
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except (ValueError, RecursionError) as exc:
                raise ValueError(f"Invalid JSON at line {line_number}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"Expected a document object at line {line_number}")
            url = record.get("url")
            if not isinstance(url, str) or url not in requested:
                continue
            try:
                document = WebsiteDocument.model_validate(record)
            except ValidationError as exc:
                # Pydantic's full error string can expose the imported text.
                raise ValueError(
                    f"Invalid selected document at line {line_number}; check its "
                    "URL, source ID/type, checksum, fetch date, labels, title, and text"
                ) from exc
            if url in selected and selected[url] != document:
                raise ValueError(f"Conflicting selected records at line {line_number}")
            selected[url] = document

    if missing := requested - selected.keys():
        raise ValueError("Requested URL(s) missing from extraction: " + ", ".join(sorted(missing)))
    return [selected[url] for url in urls]


def prepare_chunks(documents: list[WebsiteDocument | SuppliedDocument]) -> list[dict]:
    """Reuse the seed chunker; no chunk becomes authorized by being prepared."""
    return [
        chunk
        for document in documents
        for chunk in chunk_record(document.model_dump(mode="json"))
    ]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Saved crawler JSONL file")
    parser.add_argument(
        "--url", action="append", required=True,
        help=f"Exact URL; repeat for up to {MAX_SELECTED_DOCUMENTS} documents",
    )
    parser.add_argument(
        "--output", type=Path,
        help="Optional new chunk JSONL file; existing files are refused",
    )
    arguments = parser.parse_args(argv)

    try:
        documents = load_selected_documents(arguments.input, arguments.url)
        chunks = prepare_chunks(documents)
        if arguments.output:
            # Finish validation and serialization before creating an output file.
            content = "".join(json.dumps(chunk, ensure_ascii=False) + "\n" for chunk in chunks)
            arguments.output.parent.mkdir(parents=True, exist_ok=True)
            with arguments.output.open("x", encoding="utf-8") as stream:
                stream.write(content)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    print("Phase 5 — Step 1: website import preparation")
    for document in documents:
        count = sum(chunk["source_id"] == document.source_id for chunk in chunks)
        print(f"\nURL: {document.url}")
        print(f"Source ID: {document.source_id}")
        print(f"Content checksum: {document.content_sha256}")
        print(f"Fetched at: {document.fetched_at.isoformat()}")
        print(f"Words: {len(document.text.split())}; chunks: {count}")
    print(f"\nPrepared {len(documents)} document(s), {len(chunks)} chunk(s).")
    print(f"Chunk settings: {MAX_WORDS} words maximum, {OVERLAP_WORDS} words overlap.")
    if arguments.output:
        print(f"Saved local chunks to {arguments.output}")
    else:
        print("Preview only; use --output to save local chunks.")
    print("No sources registered, models called, or Qdrant points changed.")


if __name__ == "__main__":
    main()
