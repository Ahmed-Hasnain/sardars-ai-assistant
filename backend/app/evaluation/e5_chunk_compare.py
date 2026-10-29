"""Offline comparison of the frozen E5 source snapshot; never writes an index.

Run with a private source_records.jsonl export and the saved full-site cases.
The proxy metrics test answer-bearing chunk locality, not vector source ranking.
"""

import argparse
from collections import Counter
import json
from pathlib import Path
from time import perf_counter

from app.ingestion.chunking import chunk_record
from app.retrieval.rerank import _terms


def compare(records: Path, cases: Path) -> dict:
    sources = {row["url"]: row for row in map(json.loads, records.read_text().splitlines())}
    definitions = json.loads(cases.read_text())
    totals = Counter()
    case_rows = []
    started = perf_counter()
    for record in sources.values():
        old = chunk_record(record)
        new = chunk_record(record, structure_aware=True)
        totals["sources"] += 1
        totals["baseline_chunks"] += len(old)
        totals["structure_chunks"] += len(new)
        totals["changed_sources"] += [item["text"] for item in old] != [item["text"] for item in new]
        totals[f"baseline_{record['source_type']}_chunks"] += len(old)
        totals[f"structure_{record['source_type']}_chunks"] += len(new)
    for case in definitions:
        url = case.get("expected_source")
        if not url or url not in sources:
            continue
        record = sources[url]
        row = {"id": case["id"], "source_type": record["source_type"]}
        terms = _terms(case["question"])
        expected = [value.casefold() for value in case.get("answer_contains", [])]
        for name, aware in (("baseline", False), ("structure", True)):
            chunks = chunk_record(record, structure_aware=aware)
            row[name] = {
                "chunks": len(chunks),
                "max_query_terms_in_one_chunk": max((len(terms & _terms(c["text"])) for c in chunks), default=0),
                "all_expected_phrases_in_one_chunk": any(
                    all(phrase in c["text"].casefold() for phrase in expected) for c in chunks
                ) if expected else None,
            }
        case_rows.append(row)
    return {"totals": dict(totals), "cases": case_rows,
            "comparison_ms": round((perf_counter() - started) * 1000, 1),
            "limitation": "Offline locality proxy; no embeddings, retrieval ranking, or answer latency measured."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("records", type=Path)
    parser.add_argument("cases", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    with args.report.open("x", encoding="utf-8") as stream:
        json.dump(compare(args.records, args.cases), stream, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
