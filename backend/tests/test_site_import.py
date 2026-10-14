"""Controlled-import policy, transactions, CLI output, and retrieval compatibility."""

from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import sys
from types import ModuleType

import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.db.base import Base
from app.db.models import SourceRegistration
from app.ingestion.import_site import main
from app.ingestion.site_documents import WebsiteDocument
from app.ingestion.site_import import AUTHORIZATION_BASIS, apply_import, plan_import
from app.ingestion.site_index import IndexingError, WebsiteIndexer
from app.retrieval.authorization import authorized_points
from app.retrieval.seed_config import DIMENSIONS, MODEL


ABOUT_URL = "https://sardarandco.com/pages/about-us"
PRODUCT_URL = "https://sardarandco.com/products/shower-niche-pakistan"


def _document(url: str = ABOUT_URL, words: int = 177) -> WebsiteDocument:
    text = " ".join(f"word{index}" for index in range(words))
    return WebsiteDocument.model_validate({
        "source_id": sha256(url.encode()).hexdigest(),
        "source_type": "products" if "/products/" in url else "pages",
        "url": url, "visibility": "public", "review_status": "pending",
        "title": "Test document", "fetched_at": "2026-10-12T12:32:58+00:00",
        "text": text, "content_sha256": sha256(text.encode()).hexdigest(),
    })


def _settings() -> Settings:
    return Settings(_env_file=None, db_user="test", db_name="test", db_password="test")


@pytest.fixture
def sessions(tmp_path: Path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    try:
        yield sessionmaker(bind=engine)
    finally:
        engine.dispose()


def _register(sessions, document: WebsiteDocument, **changes: object) -> None:
    values = {
        "source_id": document.source_id, "url": document.url,
        "source_type": document.source_type, "visibility": "public",
        "content_sha256": document.content_sha256, "is_active": True,
        "authorization_basis": "existing_authorization",
        **changes,
    }
    with sessions.begin() as db:
        db.add(SourceRegistration(**values))


class FakeIndex:
    def __init__(self):
        self.checked = False
        self.points: dict[str, dict] = {}
        self.batches = 0

    def check_collection(self) -> None:
        self.checked = True

    def upsert_chunks(self, chunks: list[dict], authorization: dict[str, str]) -> None:
        self.batches += 1
        for chunk in chunks:
            self.points[chunk["id"]] = {
                "payload": {**chunk, "review_status": "approved", "prototype_only": False,
                            "approval_basis": authorization[chunk["source_id"]]},
            }


def test_preview_is_read_only_and_reports_existing_and_new_sources(sessions) -> None:
    documents = [_document(), _document(PRODUCT_URL, 32)]
    _register(sessions, documents[0])
    with sessions() as db:
        result = plan_import(db, documents)
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(SourceRegistration)) == 1
    assert result.status == "preview" and result.indexed_chunks == 0
    assert result.new_sources == 1
    assert [source.registration for source in result.sources] == ["existing", "new"]
    assert [source.chunks for source in result.sources] == [2, 1]


def test_repeat_import_preserves_registrations_provenance_and_chunk_ids(sessions) -> None:
    documents = [_document(), _document(PRODUCT_URL, 32)]
    _register(sessions, documents[0])
    index = FakeIndex()
    with sessions.begin() as db:
        result = apply_import(db, documents, index)
    with sessions.begin() as db:
        repeated = apply_import(db, documents, index)
    with sessions() as db:
        sources = list(db.scalars(select(SourceRegistration)))
        assert len(sources) == 2
        assert db.get(SourceRegistration, documents[0].source_id).authorization_basis == "existing_authorization"
        assert db.get(SourceRegistration, documents[1].source_id).authorization_basis == AUTHORIZATION_BASIS
        assert len(authorized_points(db, "staff", list(index.points.values()))) == 3
    assert index.checked and len(index.points) == 3
    assert result.new_sources == 1 and result.indexed_chunks == 3
    assert repeated.new_sources == 0 and repeated.indexed_chunks == 3
    assert index.batches == 2  # Unchanged-content skipping is Step 3.


@pytest.mark.parametrize("changes", [
    {"is_active": False}, {"visibility": "staff"}, {"visibility": "admin"},
    {"content_sha256": "a" * 64}, {"source_type": "articles"},
    {"source_id": "b" * 64}, {"url": "https://sardarandco.com/pages/different"},
])
def test_conflict_or_disablement_blocks_the_whole_selection_before_network_access(sessions, changes: dict) -> None:
    documents = [_document(), _document(PRODUCT_URL, 32)]
    _register(sessions, documents[1], **changes)
    index = FakeIndex()
    with pytest.raises(ValueError):
        with sessions.begin() as db:
            apply_import(db, documents, index)
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(SourceRegistration)) == 1
        source = db.scalar(select(SourceRegistration))
        assert all(getattr(source, key) == value for key, value in changes.items())
    assert not index.checked and not index.points


@pytest.mark.parametrize("documents", [[], [_document()] * 2, [_document()] * 11])
def test_service_enforces_selection_bounds_and_uniqueness(sessions, documents: list[WebsiteDocument]) -> None:
    with sessions() as db, pytest.raises(ValueError):
        plan_import(db, documents)


def test_real_http_adapter_commits_registration_only_after_index_confirmation(sessions) -> None:
    document = _document()
    points = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"result": {"config": {"params": {
                "vectors": {"size": DIMENSIONS, "distance": "Cosine"},
            }}}})
        body = json.loads(request.content)
        if request.url.path == "/api/embed":
            assert body["model"] == MODEL and body["truncate"] is False
            return httpx.Response(200, json={"embeddings": [[0.1] * DIMENSIONS for _ in body["input"]]})
        assert request.url.params["wait"] == "true"
        points.extend(body["points"])
        # A separate reader cannot use new-source vectors before PG commits.
        with sessions() as reader:
            assert authorized_points(reader, "staff", points) == []
        return httpx.Response(200, json={"status": "ok", "result": {"status": "completed"}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with sessions.begin() as db:
            result = apply_import(db, [document], WebsiteIndexer(_settings(), client))
    with sessions() as db:
        assert len(authorized_points(db, "staff", points)) == 2
    assert result.status == "completed" and result.new_sources == 1
    assert all(point["payload"]["embedding_model"] == MODEL for point in points)
    assert all(datetime.fromisoformat(point["payload"]["fetched_at"]) == document.fetched_at for point in points)


def test_partial_vector_failure_rolls_back_new_registration_and_orphans_are_ineligible(sessions) -> None:
    class PartialFailure(FakeIndex):
        def upsert_chunks(self, chunks: list[dict], authorization: dict[str, str]) -> None:
            super().upsert_chunks(chunks[:1], authorization)
            raise IndexingError("Vector write failed")

    document = _document()
    index = PartialFailure()
    with pytest.raises(IndexingError):
        with sessions.begin() as db:
            apply_import(db, [document], index)
    with sessions() as db:
        assert db.get(SourceRegistration, document.source_id) is None
        assert authorized_points(db, "staff", list(index.points.values())) == []
    assert len(index.points) == 1
    with sessions.begin() as db:
        assert apply_import(db, [document], FakeIndex()).status == "completed"


def test_cli_preview_apply_and_safe_failure_reports(sessions, tmp_path: Path, monkeypatch, capsys) -> None:
    document = _document()
    source = tmp_path / "input.jsonl"
    source.write_text(document.model_dump_json() + "\n", encoding="utf-8")
    module = ModuleType("app.db.session")
    module.SessionLocal = sessions
    monkeypatch.setitem(sys.modules, "app.db.session", module)
    monkeypatch.setattr("app.ingestion.import_site.Settings", _settings)
    index = FakeIndex()
    monkeypatch.setattr("app.ingestion.import_site.WebsiteIndexer", lambda *_args: index)
    arguments = ["--input", str(source), "--url", ABOUT_URL]

    main(arguments)
    preview = json.loads(capsys.readouterr().out)
    assert preview["status"] == "preview" and preview["new_sources"] == 1
    assert not index.checked
    main([*arguments, "--apply"])
    completed = json.loads(capsys.readouterr().out)
    assert completed["status"] == "completed" and completed["indexed_chunks"] == 2

    def unavailable(*_args, **_kwargs):
        raise IndexingError("Local embedding or vector service unavailable")

    monkeypatch.setattr(index, "check_collection", unavailable)
    with pytest.raises(SystemExit) as error:
        main([*arguments, "--apply"])
    assert error.value.code == 1
    failed = json.loads(capsys.readouterr().err)
    assert failed["status"] == "failed"
    assert "unavailable" in failed["error"]


def test_cli_database_error_does_not_echo_connection_secrets(tmp_path: Path, monkeypatch, capsys) -> None:
    from sqlalchemy.exc import OperationalError

    source = tmp_path / "input.jsonl"
    source.write_text(_document().model_dump_json() + "\n", encoding="utf-8")
    monkeypatch.setattr("app.ingestion.import_site.Settings", _settings)
    module = ModuleType("app.db.session")

    def unavailable():
        raise OperationalError("SECRET_CONNECTION_STRING", {}, Exception("SECRET_PASSWORD"))

    module.SessionLocal = unavailable
    monkeypatch.setitem(sys.modules, "app.db.session", module)
    with pytest.raises(SystemExit):
        main(["--input", str(source), "--url", ABOUT_URL])
    output = capsys.readouterr().err
    assert "SECRET" not in output
    assert json.loads(output)["status"] == "failed"
