"""Phase 5 import preparation: integrity, bounds, provenance, and safe failures."""

from hashlib import sha256
import json
from pathlib import Path

from pydantic import ValidationError
import pytest

from app.ingestion.prepare_site import load_selected_documents, main, prepare_chunks
from app.ingestion.site_documents import WebsiteDocument


ABOUT_URL = "https://sardarandco.com/pages/about-us"
PRODUCT_URL = "https://sardarandco.com/products/shower-niche-pakistan"


def _record(url: str = ABOUT_URL, text: str = "Sample descriptive text for a test document.") -> dict:
    return {
        "source_id": sha256(url.encode()).hexdigest(),
        "source_type": "products" if "/products/" in url else "pages",
        "visibility": "public",
        "review_status": "pending",
        "title": "Sample document",
        "url": url,
        "fetched_at": "2026-10-12T12:32:58+00:00",
        "content_sha256": sha256(text.encode()).hexdigest(),
        "text": text,
    }


def _write(path: Path, records: list[dict]) -> Path:
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    return path


@pytest.mark.parametrize(("field", "value"), [
    ("source_id", "a" * 64),
    ("content_sha256", "b" * 64),
    ("text", "Changed text with an obsolete checksum."),
    ("title", "   "),
    ("source_type", "products"),
    ("url", "https://other.example/pages/about-us"),
    ("visibility", "admin"),
    ("review_status", "approved"),
    ("fetched_at", "2026-10-12T12:32:58"),
    ("fetched_at", 1_760_000_000),
    ("text", "x" * 50_001),
    ("unexpected_field", "untrusted extra metadata"),
])
def test_document_rejects_invalid_identity_content_and_metadata(field: str, value: object) -> None:
    record = _record()
    record[field] = value

    with pytest.raises(ValidationError):
        WebsiteDocument.model_validate(record)


@pytest.mark.parametrize("text", ["   ", "x " * 10_001])
def test_blank_or_excessive_word_count_is_rejected_even_with_matching_checksum(text: str) -> None:
    with pytest.raises(ValidationError):
        WebsiteDocument.model_validate(_record(text=text))


def test_selection_preserves_requested_order_and_does_not_import_other_records(tmp_path: Path) -> None:
    unselected = _record("https://sardarandco.com/pages/contact")
    unselected["content_sha256"] = "not validated because it was not selected"
    path = _write(tmp_path / "input.jsonl", [_record(), unselected, _record(PRODUCT_URL)])

    documents = load_selected_documents(path, [PRODUCT_URL, ABOUT_URL])

    assert [document.url for document in documents] == [PRODUCT_URL, ABOUT_URL]
    assert all(document.fetched_at.utcoffset() is not None for document in documents)


def test_identical_duplicate_is_deduplicated_but_conflicting_version_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path / "input.jsonl", [_record(), _record()])
    assert len(load_selected_documents(path, [ABOUT_URL])) == 1

    _write(path, [_record(), _record(text="A different valid version of this document.")])
    with pytest.raises(ValueError, match="Conflicting selected records"):
        load_selected_documents(path, [ABOUT_URL])


@pytest.mark.parametrize("urls", [[], [ABOUT_URL, ABOUT_URL], ["https://other.example/pages/about-us"], [ABOUT_URL] * 11])
def test_selection_must_be_explicit_supported_unique_and_bounded(tmp_path: Path, urls: list[str]) -> None:
    with pytest.raises(ValueError):
        load_selected_documents(_write(tmp_path / "input.jsonl", [_record()]), urls)


@pytest.mark.parametrize("setting", ["MAX_INPUT_BYTES", "MAX_RECORD_BYTES", "MAX_RECORDS"])
def test_processing_limits_fail_before_preparing_an_import(tmp_path: Path, monkeypatch, setting: str) -> None:
    path = _write(tmp_path / "input.jsonl", [_record(), _record(PRODUCT_URL)])
    monkeypatch.setattr(f"app.ingestion.prepare_site.{setting}", 1)

    with pytest.raises(ValueError, match="limit"):
        load_selected_documents(path, [ABOUT_URL])


@pytest.mark.parametrize("content", [
    "not JSON\n", "[]\n", '{"url":\n', '{"url": "\udcff"}\n',
    "[" * 1100 + "0" + "]" * 1100 + "\n",
])
def test_malformed_extraction_is_rejected(tmp_path: Path, content: str) -> None:
    path = tmp_path / "input.jsonl"
    path.write_bytes(content.encode("utf-8", errors="surrogateescape"))

    with pytest.raises(ValueError):
        load_selected_documents(path, [ABOUT_URL])


def test_chunks_preserve_provenance_and_have_stable_ids_across_content_updates(tmp_path: Path) -> None:
    original = _record(text=" ".join(f"word{index}" for index in range(180)))
    path = _write(tmp_path / "input.jsonl", [original])
    chunks = prepare_chunks(load_selected_documents(path, [ABOUT_URL]))

    assert len(chunks) == 2
    assert all(len(chunk["text"].split()) <= 100 for chunk in chunks)
    assert chunks[0]["text"].split()[-15:] == chunks[1]["text"].split()[:15]
    assert all(chunk["source_id"] == original["source_id"] for chunk in chunks)
    assert all(chunk["content_sha256"] == original["content_sha256"] for chunk in chunks)
    assert all(chunk["url"] == ABOUT_URL and chunk["review_status"] == "pending" for chunk in chunks)

    changed = _record(text="A much shorter replacement document.")
    _write(path, [changed])
    replacement = prepare_chunks(load_selected_documents(path, [ABOUT_URL]))
    assert replacement[0]["id"] == chunks[0]["id"]
    assert replacement[0]["content_sha256"] != chunks[0]["content_sha256"]
    # Removing the obsolete second chunk is a later synchronization checkpoint.
    assert len(replacement) == 1


def test_cli_previews_and_saves_local_chunks_without_overwriting_files(tmp_path: Path, capsys) -> None:
    source = _write(tmp_path / "input.jsonl", [_record()])
    arguments = ["--input", str(source), "--url", ABOUT_URL]
    main(arguments)
    assert "Preview only" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == [source]

    output = tmp_path / "chunks.jsonl"
    main([*arguments, "--output", str(output)])
    saved = output.read_text()
    assert json.loads(saved)["content_sha256"] == _record()["content_sha256"]
    with pytest.raises(SystemExit) as error:
        main([*arguments, "--output", str(output)])
    assert error.value.code == 2
    assert output.read_text() == saved


def test_cli_missing_or_invalid_selected_document_creates_no_output_and_hides_content(tmp_path: Path, capsys) -> None:
    sensitive_text = "PRIVATE_TEST_CONTENT_MUST_NOT_APPEAR_IN_DIAGNOSTICS"
    record = _record(text=sensitive_text)
    record["content_sha256"] = "b" * 64
    source = _write(tmp_path / "input.jsonl", [record])
    output = tmp_path / "chunks.jsonl"

    with pytest.raises(SystemExit) as error:
        main(["--input", str(source), "--url", ABOUT_URL, "--output", str(output)])
    assert error.value.code == 2
    assert sensitive_text not in capsys.readouterr().err
    assert not output.exists()

    with pytest.raises(ValueError, match="missing from extraction"):
        load_selected_documents(source, [PRODUCT_URL])
