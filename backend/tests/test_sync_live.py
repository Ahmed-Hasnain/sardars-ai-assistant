"""Opt-in real PostgreSQL/Qdrant/Ollama lifecycle in disposable namespaces.

Run: SARDARS_RUN_SYNC_LIVE=1 PYTHONPATH=backend backend/.venv/bin/python -m
     pytest -q -s backend/tests/test_sync_live.py
No live source registrations or seed vectors are changed.
"""

from hashlib import sha256
import os
from urllib.parse import urlparse
from uuid import uuid4

from alembic import command
from alembic.config import Config
import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.skipif(os.environ.get("SARDARS_RUN_SYNC_LIVE") != "1", reason="opt-in local-service integration")


def test_live_migration_update_skip_removal_and_jobs(monkeypatch) -> None:
    from app.core.config import Settings
    from app.db.session import engine
    from app.db.models import IngestionJob, SourceRegistration
    from app.ingestion import site_index
    from app.ingestion.job_requests import JobRequest
    from app.ingestion.job_runner import run_job
    from app.ingestion.job_store import enqueue
    from app.ingestion.site_documents import WebsiteDocument
    from app.retrieval.authorization import authorized_points

    settings = Settings()
    assert engine.url.host in {"localhost", "127.0.0.1", "::1"}
    assert urlparse(settings.qdrant_base_url).hostname in {"localhost", "127.0.0.1", "::1"}
    assert urlparse(settings.ollama_base_url).hostname in {"localhost", "127.0.0.1", "::1"}
    namespace = "sardars_sync_test_" + uuid4().hex
    isolated = None
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{namespace}"')
    try:
        isolated = create_engine(engine.url, connect_args={"connect_timeout": 5, "options": f"-c search_path={namespace}"})
        config = Config("alembic.ini")
        with isolated.begin() as connection:
            config.attributes.update(connection=connection)
            # Exercise legacy-row preservation across the actual schema upgrade.
            command.upgrade(config, "f34a2d6c91b7")
            connection.exec_driver_sql(
                "INSERT INTO source_registrations (source_id, url, source_type, visibility, content_sha256, authorization_basis) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                ("a" * 64, "https://sardarandco.com/pages/legacy-test", "pages", "public", "b" * 64, "isolated_test"),
            )
            command.upgrade(config, "head")
            assert connection.exec_driver_sql("SELECT index_status, index_generation FROM source_registrations").one() == ("ready", None)
            command.check(config)
        print("Real PostgreSQL migration and metadata check passed")
        sessions = sessionmaker(bind=isolated)
        monkeypatch.setattr(site_index, "COLLECTION", namespace)
        url = "https://sardarandco.com/pages/sync-test-document"

        def doc(words: int, date: str) -> WebsiteDocument:
            text = " ".join(f"isolated-test-word-{index}" for index in range(words))
            return WebsiteDocument.model_validate({
                "source_id": sha256(url.encode()).hexdigest(), "url": url, "source_type": "pages",
                "visibility": "public", "review_status": "pending", "title": "Isolated synchronization test",
                "fetched_at": date, "text": text, "content_sha256": sha256(text.encode()).hexdigest(),
            })

        with httpx.Client(timeout=settings.ollama_timeout_seconds) as client:
            base = settings.qdrant_base_url.rstrip('/') + "/collections/" + namespace
            client.put(base, json={"vectors": {"size": site_index.DIMENSIONS, "distance": "Cosine"}}).raise_for_status()
            try:
                first = doc(177, "2026-10-12T12:00:00+00:00")
                job_id = enqueue(sessions, JobRequest(operation="import", documents=[first]))
                assert run_job(sessions, job_id, site_index.WebsiteIndexer(settings, client))["indexed_chunks"] == 2
                print("Real import: two chunks published")
                second = doc(32, "2026-10-13T12:00:00+00:00")
                updated_id = enqueue(sessions, JobRequest(operation="import", documents=[second]))
                updated = run_job(sessions, updated_id, site_index.WebsiteIndexer(settings, client))
                assert updated["updated_sources"] == 1 and updated["deleted_chunks"] == 2
                points = client.post(base + "/points/scroll", json={"limit": 10, "with_payload": True}).json()["result"]["points"]
                with sessions() as db:
                    assert len(authorized_points(db, "staff", points)) == 1
                    assert db.get(IngestionJob, updated_id).status == "completed"
                print("Real update: old chunks removed, one replacement authorized")
                skipped_id = enqueue(sessions, JobRequest(operation="import", documents=[second]))
                skipped = run_job(sessions, skipped_id, site_index.WebsiteIndexer(settings, client))
                assert skipped["indexed_chunks"] == 0 and skipped["skipped_chunks"] == 1
                removed_id = enqueue(sessions, JobRequest(operation="remove", urls=[url]))
                removed = run_job(sessions, removed_id, site_index.WebsiteIndexer(settings, client))
                assert removed["deleted_chunks"] == 1
                assert client.get(base).json()["result"]["points_count"] == 0
                with sessions() as db:
                    source = db.get(SourceRegistration, second.source_id)
                    assert not source.is_active and source.index_status == "removed"
                    assert db.get(IngestionJob, removed_id).status == "completed"
                print("Real skip/removal/job lifecycle passed")
            finally:
                client.delete(base).raise_for_status()
    finally:
        if isolated is not None:
            isolated.dispose()
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{namespace}" CASCADE')


def test_live_authenticated_upload_private_retrieval_and_removal(monkeypatch, tmp_path) -> None:
    from fastapi.testclient import TestClient
    from app.api.ingestion import get_settings
    from app.auth.security import hash_password
    from app.core.config import Settings
    from app.db.session import engine, get_db
    from app.db.models import User
    from app.ingestion import site_index
    from app.main import app
    from app.retrieval import search_seed
    from test_ingestion_extraction import pdf

    settings = Settings(ingestion_storage_dir=tmp_path / "originals")
    assert engine.url.host in {"localhost", "127.0.0.1", "::1"}
    assert urlparse(settings.qdrant_base_url).hostname in {"localhost", "127.0.0.1", "::1"}
    assert urlparse(settings.ollama_base_url).hostname in {"localhost", "127.0.0.1", "::1"}
    namespace = "sardars_sync_test_" + uuid4().hex
    isolated = None
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{namespace}"')
    try:
        isolated = create_engine(engine.url, connect_args={"connect_timeout": 5, "options": f"-c search_path={namespace}"})
        config = Config("alembic.ini")
        with isolated.begin() as connection:
            config.attributes.update(connection=connection)
            command.upgrade(config, "head")
            command.check(config)
        sessions = sessionmaker(bind=isolated)
        with sessions.begin() as db:
            for role in ("admin", "staff"):
                db.add(User(email=role + "@isolated.test", role=role, password_hash=hash_password("isolated test password")))
        monkeypatch.setattr(site_index, "COLLECTION", namespace)
        monkeypatch.setattr(search_seed, "COLLECTION", namespace)

        def override_db():
            with sessions() as db:
                yield db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_settings] = lambda: settings
        with httpx.Client(timeout=30) as qdrant:
            base = settings.qdrant_base_url.rstrip('/') + "/collections/" + namespace
            qdrant.put(base, json={"vectors": {"size": site_index.DIMENSIONS, "distance": "Cosine"}}).raise_for_status()
            try:
                with TestClient(app) as client:
                    headers = {}
                    for role in ("admin", "staff"):
                        token = client.post("/api/v1/auth/login", json={"email": role + "@isolated.test", "password": "isolated test password"}).json()["access_token"]
                        headers[role] = {"Authorization": "Bearer " + token}
                    assert client.post("/api/v1/ingestion/files", files={"file": ("guide.md", b"test")}).status_code == 401
                    uploaded = client.post("/api/v1/ingestion/files", headers=headers["staff"], files={"file": ("guide.md", b"Sardars mentions premium brands like Demobrand.")})
                    assert uploaded.status_code == 200, uploaded.text
                    result = uploaded.json()
                    identity, file_link = result["sources"][0]["source_id"], result["sources"][0]["url"]
                    assert client.get(file_link, headers=headers["staff"]).status_code == 200
                    answer = client.post("/api/v1/ask", headers=headers["staff"], json={"message": "What is Demobrand?"})
                    assert answer.status_code == 200 and answer.json()["sources"][0]["url"] == file_link
                    job = client.get("/api/v1/ingestion/jobs/" + result["job_id"], headers=headers["staff"])
                    assert job.json()["status"] == "completed" and "storage_key" not in job.text
                    private = client.post("/api/v1/ingestion/files", headers=headers["admin"], data={"visibility": "admin"}, files={"file": ("private.pdf", pdf("Sardars mentions premium brands like Vaultbrand."))})
                    assert private.status_code == 200, private.text
                    assert client.get(private.json()["sources"][0]["url"], headers=headers["staff"]).status_code == 404
                    denied = client.post("/api/v1/ask", headers=headers["staff"], json={"message": "What is Vaultbrand?"})
                    assert denied.status_code == 200 and denied.json()["sources"] == []
                    permitted = client.post("/api/v1/ask", headers=headers["admin"], json={"message": "What is Vaultbrand?"})
                    assert permitted.status_code == 200 and permitted.json()["sources"]
                    # The owner-authorized website is fetched and indexed only
                    # in this disposable collection, not the live chat seed.
                    page = client.post("/api/v1/ingestion/urls", headers=headers["admin"], json={"url": "https://sardarandco.com/pages/about-us", "visibility": "public"})
                    assert page.status_code == 200, page.text
                    assert page.json()["indexed_chunks"] == 2
                    website_answer = client.post("/api/v1/ask", headers=headers["staff"], json={"message": "What is Bongio?"})
                    assert website_answer.status_code == 200 and website_answer.json()["sources"][0]["url"] == "https://sardarandco.com/pages/about-us"
                    updated = client.post("/api/v1/ingestion/files", headers=headers["staff"], data={"source_id": identity}, files={"file": ("guide.md", b"Sardars mentions premium brands like Newbrand.")})
                    assert updated.status_code == 200 and updated.json()["updated_sources"] == 1
                    assert client.get(file_link, headers=headers["staff"]).content == b"Sardars mentions premium brands like Newbrand."
                    removed = client.delete("/api/v1/ingestion/sources/" + identity, headers=headers["staff"])
                    assert removed.status_code == 200 and client.get(file_link, headers=headers["staff"]).status_code == 404
                    assert qdrant.get(base).json()["result"]["points_count"] == 3
                    print("Real authenticated URL/Markdown/PDF import, cited retrieval, admin/staff boundaries, update, removal, and job status passed")
            finally:
                qdrant.delete(base).raise_for_status()
    finally:
        app.dependency_overrides.clear()
        if isolated is not None:
            isolated.dispose()
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{namespace}" CASCADE')
