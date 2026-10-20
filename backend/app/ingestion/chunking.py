import json
from pathlib import Path
import re
from uuid import NAMESPACE_URL, uuid5

MAX_WORDS = 100
OVERLAP_WORDS = 15
MAX_FAQ_WORDS = 120
FAQ_BLOCK = re.compile(r"^[A-Z][A-Z0-9_-]{2,48}-FAQ-\d{3,5}\s*\|\s*.+\?\s*\nAnswer:\s*", re.I)


def _sliding_groups(words: list[str]) -> list[list[str]]:
    groups = []
    for start in range(0, len(words), MAX_WORDS - OVERLAP_WORDS):
        groups.append(words[start:start + MAX_WORDS])
        if start + MAX_WORDS >= len(words):
            break
    return groups


def _word_groups(text: str) -> list[list[str]]:
    """Keep a short, clearly labelled FAQ question with its answer."""
    blocks = re.split(r"\n\s*\n", text.strip())
    if not any(FAQ_BLOCK.match(block) for block in blocks):
        return _sliding_groups(text.split())

    groups: list[list[str]] = []
    ordinary: list[str] = []

    def flush_ordinary() -> None:
        if not ordinary:
            return
        groups.extend(_sliding_groups(ordinary))
        ordinary.clear()

    for block in blocks:
        words = block.split()
        if FAQ_BLOCK.match(block) and len(words) <= MAX_FAQ_WORDS:
            flush_ordinary()
            groups.append(words)
        else:
            ordinary.extend(words)
    flush_ordinary()
    return groups


def chunk_record(record: dict) -> list[dict]:
    chunks = []
    for index, chunk_words in enumerate(_word_groups(record["text"])):
        chunk = {
            "id": str(uuid5(NAMESPACE_URL, f"{record['source_id']}:{index}")),
            "source_id": record["source_id"],
            "source_type": record["source_type"],
            "visibility": record["visibility"],
            "review_status": record["review_status"],
            "title": record["title"],
            "url": record["url"],
            "fetched_at": record["fetched_at"],
            "content_sha256": record["content_sha256"],
            "chunk_index": index,
            "text": " ".join(chunk_words),
        }
        if record.get("derivation") is not None:
            chunk["derivation"] = record["derivation"]
        chunks.append(chunk)

    return chunks


def main() -> None:
    source = Path("data/extracted/rag_seed.jsonl")
    destination = Path("data/extracted/rag_seed_chunks.jsonl")

    with source.open(encoding="utf-8") as input_file, destination.open(
        "w", encoding="utf-8"
    ) as output_file:
        for line in input_file:
            record = json.loads(line)
            for chunk in chunk_record(record):
                output_file.write(json.dumps(chunk, ensure_ascii=False) + "\n")

    print(f"Wrote chunks to {destination}")


if __name__ == "__main__":
    main()
