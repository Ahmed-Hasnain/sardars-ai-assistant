import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

MAX_WORDS = 100
OVERLAP_WORDS = 15


def chunk_record(record: dict) -> list[dict]:
    words = record["text"].split()
    chunks = []
    step = MAX_WORDS - OVERLAP_WORDS

    for index, start in enumerate(range(0, len(words), step)):
        chunk_words = words[start : start + MAX_WORDS]
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

        if start + MAX_WORDS >= len(words):
            break

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
