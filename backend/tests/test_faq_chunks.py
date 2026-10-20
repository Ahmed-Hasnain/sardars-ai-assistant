from hashlib import sha256

from app.ingestion.chunking import chunk_record


def _record(text: str) -> dict:
    url = "/api/v1/ingestion/files/24716db5-f918-4512-b49d-0c035f1f13b3"
    return {
        "source_id": sha256(url.encode()).hexdigest(), "source_type": "text",
        "visibility": "staff", "review_status": "approved",
        "title": "Company FAQ", "url": url, "fetched_at": "2026-10-20T00:00:00Z",
        "content_sha256": sha256(text.encode()).hexdigest(), "text": text,
    }


def test_faq_questions_stay_with_their_answers() -> None:
    text = (
        "Company FAQ\n\n"
        + " ".join(["Introduction"] * 92) + "\n\n"
        + "SARDARS-FAQ-001 | Is Sardar and Co the same business as Sardars?\n"
        + "Answer: These names are used for the same company website.\n"
        + "Question origin: anticipated_customer_question\n\n"
        + "SARDARS-FAQ-002 | Does Sardars manufacture every product?\n"
        + "Answer: Sardars sources products from other manufacturers.\n"
        + "Question origin: anticipated_customer_question"
    )
    chunks = chunk_record(_record(text))
    first = [chunk for chunk in chunks if "SARDARS-FAQ-001" in chunk["text"]]
    second = [chunk for chunk in chunks if "SARDARS-FAQ-002" in chunk["text"]]
    assert len(first) == len(second) == 1
    assert "Answer: These names are used" in first[0]["text"]
    assert "Answer: Sardars sources" in second[0]["text"]
    assert "SARDARS-FAQ-002" not in first[0]["text"]


def test_regular_documents_keep_overlapping_chunks() -> None:
    chunks = chunk_record(_record(" ".join(f"word{number}" for number in range(190))))
    assert [len(chunk["text"].split()) for chunk in chunks] == [100, 100, 20]
    assert chunks[0]["text"].split()[-15:] == chunks[1]["text"].split()[:15]
