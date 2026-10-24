"""Authenticated API lifecycle with real extraction and simulated local models/index."""

from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.api.ingestion import get_settings
from app.auth.security import hash_password
from app.core.config import Settings
from app.db.base import Base
from app.db.models import IngestionJob, SourceRegistration, User
from app.db.session import get_db
from app.ingestion.job_runner import JobFailed, run_job
from app.ingestion.site_index import WebsiteIndexer
from app.llm.base import ChatResult, ToolChatResult
from app.main import app
from app.services import ingestion as service
from test_sync_jobs import Services


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'api.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    settings = Settings(_env_file=None, db_user="test", db_name="test", db_password="test", ingestion_storage_dir=tmp_path / "uploads")
    services = Services()

    def db_dependency():
        with sessions() as db:
            yield db

    def execute(factory, config, job_id, *, retry=False):
        try:
            with httpx.Client(transport=httpx.MockTransport(services.handle)) as client:
                return run_job(factory, job_id, WebsiteIndexer(config, client), retry=retry)
        except JobFailed as exc:
            raise HTTPException(503, {"job_id": exc.job_id, "status": "failed", "error": str(exc)}) from exc
        except ValueError as exc:
            raise HTTPException(409, {"job_id": job_id, "error": str(exc)}) from exc

    monkeypatch.setattr(service, "execute", execute)
    app.dependency_overrides[get_db] = db_dependency
    app.dependency_overrides[get_settings] = lambda: settings
    with sessions.begin() as db:
        for email, role in (("staff@test.local", "staff"), ("other@test.local", "staff"), ("admin@test.local", "admin")):
            db.add(User(email=email, role=role, password_hash=hash_password("test password only")))
    try:
        with TestClient(app) as client:
            headers = {}
            for name in ("staff", "other", "admin"):
                token = client.post("/api/v1/auth/login", json={"email": name + "@test.local", "password": "test password only"}).json()["access_token"]
                headers[name] = {"Authorization": "Bearer " + token}
            yield client, sessions, settings, services, headers
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def upload(client, headers, text=b"Sardars mentions premium brands like Testbrand.", **fields):
    return client.post("/api/v1/ingestion/files", headers=headers, files={"file": ("catalogue.txt", text, "text/plain")}, data=fields)


def test_authentication_precedes_extraction_and_storage(runtime, monkeypatch):
    client, sessions, settings, _, _ = runtime
    extract = AsyncMock()
    monkeypatch.setattr(service, "extract_file", extract)
    assert upload(client, {}).status_code == 401
    assert client.post("/api/v1/ingestion/urls", json={"url": "https://sardarandco.com/pages/about-us"}).status_code == 401
    assert client.get("/api/v1/ingestion/jobs").status_code == 401
    assert client.get("/api/v1/ingestion/sources").status_code == 401
    extract.assert_not_called()
    assert not settings.ingestion_storage_dir.exists()
    with sessions() as db:
        assert list(db.scalars(select(IngestionJob))) == []


def test_file_upload_provenance_citation_download_and_job_privacy(runtime):
    client, sessions, settings, services, headers = runtime
    response = upload(client, headers["staff"])
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "completed" and result["indexed_chunks"] == 1
    identity, url = result["sources"][0]["source_id"], result["sources"][0]["url"]
    with sessions() as db:
        source = db.get(SourceRegistration, identity)
        owner = db.scalar(select(User).where(User.email == "staff@test.local"))
        assert source.visibility == "staff" and source.registered_by_user_id == owner.id
        assert source.authorization_basis == "authenticated_internal_submission"
        assert source.storage_key not in url and source.original_filename == "catalogue.txt"
        blob = settings.ingestion_storage_dir / (source.storage_key + ".blob")
        assert blob.stat().st_mode & 0o777 == 0o600
    download = client.get(url, headers=headers["other"])
    assert download.status_code == 200 and download.content == b"Sardars mentions premium brands like Testbrand."
    assert download.headers["content-disposition"] == "attachment"
    assert client.get(url).status_code == 401
    job = client.get("/api/v1/ingestion/jobs/" + result["job_id"], headers=headers["staff"])
    assert job.json()["status"] == "completed"
    assert "storage_key" not in job.text and "Testbrand" not in job.text and "run_token" not in job.text
    assert client.get("/api/v1/ingestion/jobs/" + result["job_id"], headers=headers["other"]).status_code == 404
    with patch("app.services.model_assistant.search_for_role", return_value=list(services.points.values())), \
         patch("app.api.ask.answer_model.chat_with_tools", new_callable=AsyncMock,
               return_value=ToolChatResult("READY", "fixture", (), None, None, None)), \
         patch("app.api.ask.answer_model.chat", new_callable=AsyncMock,
               return_value=ChatResult("Sardars mentions Testbrand. [1]", "fixture", None, None, None)):
        answer = client.post("/api/v1/ask", headers=headers["staff"], json={"message": "What is Testbrand?"})
    assert answer.status_code == 200 and "Testbrand" in answer.json()["answer"]
    assert answer.json()["sources"][0]["url"] == url


def test_admin_only_content_never_reaches_staff_answers_or_metadata(runtime):
    client, _, _, services, headers = runtime
    result = upload(client, headers["admin"], b"Sardars mentions premium brands like Vaultbrand.", visibility="admin").json()
    url, identity = result["sources"][0]["url"], result["sources"][0]["source_id"]
    assert client.get(url, headers=headers["staff"]).status_code == 404
    assert client.get(url, headers=headers["admin"]).status_code == 200
    assert client.get("/api/v1/ingestion/sources", headers=headers["staff"]).json() == []
    assert client.get("/api/v1/ingestion/jobs/" + result["job_id"], headers=headers["staff"]).status_code == 404
    assert client.delete("/api/v1/ingestion/sources/" + identity, headers=headers["staff"]).status_code == 404
    async def answer_from_context(messages):
        has_brand = "Vaultbrand" in messages[-2]["content"]
        return ChatResult(
            "Sardars mentions Vaultbrand. [1]" if has_brand else "I cannot verify that from available sources.",
            "fixture", None, None, None,
        )

    with (patch("app.services.model_assistant.search_for_role", return_value=list(services.points.values())),
          patch("app.api.ask.answer_model.chat_with_tools", new_callable=AsyncMock,
                return_value=ToolChatResult("READY", "fixture", (), None, None, None)),
          patch("app.api.ask.answer_model.chat", new_callable=AsyncMock,
                side_effect=answer_from_context) as model):
        denied = client.post("/api/v1/ask", headers=headers["staff"], json={"message": "What is Vaultbrand?"})
        assert denied.json()["sources"] == [] and "Vaultbrand" not in denied.json()["answer"]
        permitted = client.post("/api/v1/ask", headers=headers["admin"], json={"message": "What is Vaultbrand?"})
        assert "Vaultbrand" in permitted.json()["answer"] and permitted.json()["sources"]
        assert model.await_count == 2


@pytest.mark.parametrize("visibility", ["public", "admin"])
def test_staff_cannot_assign_admin_or_public_visibility(runtime, visibility):
    client, _, settings, _, headers = runtime
    assert upload(client, headers["staff"], visibility=visibility).status_code == 403
    assert not settings.ingestion_storage_dir.exists()


def test_update_keeps_source_identity_and_removal_revokes_access(runtime):
    client, _, _, services, headers = runtime
    first = upload(client, headers["staff"]).json()
    identity = first["sources"][0]["source_id"]
    old_ids = set(services.points)
    update = upload(client, headers["staff"], b"Sardars mentions premium brands like Newbrand.", source_id=identity)
    assert update.status_code == 200 and update.json()["updated_sources"] == 1
    assert update.json()["sources"][0]["source_id"] == identity
    assert not (old_ids & services.points.keys())
    url = first["sources"][0]["url"]
    assert b"Newbrand" in client.get(url, headers=headers["staff"]).content
    assert upload(client, headers["other"], source_id=identity).status_code == 404
    assert client.delete("/api/v1/ingestion/sources/" + identity, headers=headers["other"]).status_code == 404
    removed = client.delete("/api/v1/ingestion/sources/" + identity, headers=headers["staff"])
    assert removed.status_code == 200 and removed.json()["deleted_chunks"] == 1
    assert client.get(url, headers=headers["staff"]).status_code == 404
    assert upload(client, headers["staff"], source_id=identity).status_code == 409
    assert not services.points


def test_failed_job_retry_uses_snapshot_and_enforces_owner(runtime):
    client, sessions, _, services, headers = runtime
    services.fail_path = "/api/embed"
    failed = upload(client, headers["staff"])
    assert failed.status_code == 503
    job_id = failed.json()["detail"]["job_id"]
    assert "SECRET" not in failed.text
    status = client.get("/api/v1/ingestion/jobs/" + job_id, headers=headers["staff"]).json()
    assert status["status"] == "failed" and status["attempts"] == 1
    assert client.post("/api/v1/ingestion/jobs/" + job_id + "/retry", headers=headers["other"]).status_code == 404
    services.fail_path = None
    retried = client.post("/api/v1/ingestion/jobs/" + job_id + "/retry", headers=headers["staff"])
    assert retried.status_code == 200 and retried.json()["attempts"] == 2
    assert client.post("/api/v1/ingestion/jobs/" + job_id + "/retry", headers=headers["staff"]).status_code == 409
    assert client.get("/api/v1/ingestion/jobs", headers=headers["staff"]).json()[0]["status"] == "completed"


def test_retry_checks_current_visibility_and_submitter_role(runtime):
    client, sessions, _, services, headers = runtime
    services.fail_path = "/api/embed"
    failed = upload(client, headers["staff"]).json()["detail"]
    with sessions.begin() as db:
        job = db.get(IngestionJob, failed["job_id"])
        doc = job.request["documents"][0]
        db.get(SourceRegistration, doc["source_id"]).visibility = "admin"
    assert client.get("/api/v1/ingestion/jobs/" + failed["job_id"], headers=headers["staff"]).status_code == 404
    assert client.post("/api/v1/ingestion/jobs/" + failed["job_id"] + "/retry", headers=headers["staff"]).status_code == 404


def test_url_submission_has_owner_and_reuses_existing_source_identity(runtime, monkeypatch):
    client, _, _, services, headers = runtime
    monkeypatch.setattr(service, "extract_url", lambda url, settings: (b"<html>Test source</html>", "Test source", "Sardars mentions premium brands like Webbrand."))
    url = "https://sardarandco.com/pages/test-description"
    first = client.post("/api/v1/ingestion/urls", headers=headers["staff"], json={"url": url})
    assert first.status_code == 200, first.text
    second = client.post("/api/v1/ingestion/urls", headers=headers["staff"], json={"url": url})
    assert second.status_code == 200 and second.json()["skipped_chunks"] == 1
    assert first.json()["sources"][0]["source_id"] == second.json()["sources"][0]["source_id"]
    assert client.post("/api/v1/ingestion/urls", headers=headers["other"], json={"url": url}).status_code == 403
    assert len(services.points) == 1


@pytest.mark.parametrize("url", ["http://sardarandco.com/pages/about-us", "https://localhost/", "https://127.0.0.1/", "https://example.com/", "https://sardarandco.com/pages/about-us?token=secret", "https://user:secret@sardarandco.com/pages/about-us"])
def test_unsafe_or_unconfigured_urls_rejected_before_fetch(runtime, monkeypatch, url):
    client, _, _, _, headers = runtime
    fetch = AsyncMock()
    monkeypatch.setattr(service, "extract_url", fetch)
    assert client.post("/api/v1/ingestion/urls", headers=headers["staff"], json={"url": url}).status_code in {400, 422}
    fetch.assert_not_called()


@pytest.mark.parametrize("filename,content", [("../../secrets.txt", b"valid text"), ("payload.exe", b"valid text"), ("fake.pdf", b"not a pdf"), ("bad.txt", b"\xff"), ("empty.txt", b"")])
def test_invalid_files_leave_no_jobs_or_stored_originals(runtime, filename, content):
    client, sessions, settings, _, headers = runtime
    response = client.post("/api/v1/ingestion/files", headers=headers["staff"], files={"file": (filename, content)})
    assert response.status_code == 400, response.text
    assert not settings.ingestion_storage_dir.exists()
    with sessions() as db:
        assert list(db.scalars(select(IngestionJob))) == []


def test_upload_size_and_multipart_field_limits(runtime):
    client, _, settings, _, headers = runtime
    assert upload(client, headers["staff"], b"x" * (5 * 1024 * 1024 + 1)).status_code == 413
    assert upload(client, headers["staff"], unknown="field").status_code == 422
    response = client.post("/api/v1/ingestion/files", headers=headers["staff"], files=[("file", ("a.txt", b"a")), ("file", ("b.txt", b"b"))])
    assert response.status_code == 400
    assert client.post("/api/v1/ingestion/files", headers=headers["staff"], json={"file": "x"}).status_code == 415
    assert not settings.ingestion_storage_dir.exists()


def test_docs_empty_optional_fields_create_a_new_source_with_filename_title(runtime):
    client, sessions, _, _, headers = runtime
    response = upload(client, headers["staff"], title="", source_id="", visibility="staff")
    assert response.status_code == 200, response.text
    assert response.json()["new_sources"] == 1
    with sessions() as db:
        source = db.get(SourceRegistration, response.json()["sources"][0]["source_id"])
        assert source.title == "catalogue.txt" and source.visibility == "staff"


@pytest.mark.parametrize("fields,invalid_field", [
    ({"source_id": "PRIVATE_INVALID_INPUT"}, "source_id"),
    ({"title": "a" * 501}, "title"),
    ({"visibility": "unknown"}, "visibility"),
])
def test_invalid_metadata_identifies_fields_without_echoing_input(runtime, fields, invalid_field):
    client, sessions, settings, _, headers = runtime
    response = upload(client, headers["staff"], **fields)
    assert response.status_code == 422
    assert invalid_field in response.json()["detail"]
    assert "PRIVATE_INVALID_INPUT" not in response.text
    assert not settings.ingestion_storage_dir.exists()
    with sessions() as db:
        assert list(db.scalars(select(IngestionJob))) == []


def test_download_integrity_check_and_revocation(runtime):
    client, sessions, settings, _, headers = runtime
    result = upload(client, headers["staff"]).json()
    source_id, url = result["sources"][0]["source_id"], result["sources"][0]["url"]
    with sessions() as db:
        key = db.get(SourceRegistration, source_id).storage_key
    (settings.ingestion_storage_dir / (key + ".blob")).write_bytes(b"corrupted")
    assert client.get(url, headers=headers["staff"]).status_code == 503
    with sessions.begin() as db:
        db.scalar(select(User).where(User.email == "staff@test.local")).is_active = False
    assert client.get(url, headers=headers["staff"]).status_code == 401


def test_processing_busy_response_has_no_side_effects(runtime):
    from app.api.ingestion import _processing_slot
    client, sessions, settings, _, headers = runtime
    assert _processing_slot.acquire(blocking=False)
    try:
        response = upload(client, headers["staff"])
        assert response.status_code == 429 and response.headers["retry-after"] == "5"
        assert not settings.ingestion_storage_dir.exists()
        with sessions() as db:
            assert list(db.scalars(select(IngestionJob))) == []
    finally:
        _processing_slot.release()
    assert upload(client, headers["staff"]).status_code == 200


def test_streamed_body_limit_does_not_depend_on_content_length(runtime):
    client, _, settings, _, headers = runtime
    body = [b"x" * (1024 * 1024)] * 6
    response = client.post("/api/v1/ingestion/files", headers={**headers["staff"], "Content-Type": "multipart/form-data; boundary=test"}, content=iter(body))
    assert response.status_code == 413
    assert not settings.ingestion_storage_dir.exists()


def test_account_revocation_during_indexing_prevents_publication(runtime):
    client, sessions, _, services, headers = runtime
    def disable(request):
        if request.url.path == "/api/embed":
            with sessions.begin() as db:
                db.scalar(select(User).where(User.email == "staff@test.local")).is_active = False
    services.callback = disable
    response = upload(client, headers["staff"])
    assert response.status_code == 503
    with sessions() as db:
        assert db.scalar(select(SourceRegistration)).index_status == "failed"
        assert db.scalar(select(IngestionJob)).status == "failed"
    assert client.get("/api/v1/ingestion/jobs", headers=headers["staff"]).status_code == 401
