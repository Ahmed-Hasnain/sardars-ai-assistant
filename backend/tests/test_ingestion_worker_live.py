"""Opt-in E3 worker lifecycle in a disposable PostgreSQL schema.

Run with SARDARS_RUN_E3_LIVE=1 and SARDARS_DB_PORT pointing at a local DB.
Qdrant and Ollama calls are mocked; the application corpus is untouched.
"""

import os
from uuid import uuid4

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
from app.db.session import engine, get_db
from app.ingestion.job_store import claim, now
from app.ingestion.worker import process_one
from app.main import app
from test_sync_jobs import Services

pytestmark = pytest.mark.skipif(os.environ.get("SARDARS_RUN_E3_LIVE") != "1", reason="opt-in isolated PostgreSQL test")


def test_real_postgres_queue_recovery_update_and_revocation(tmp_path):
    namespace = "sardars_e3_test_" + uuid4().hex
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{namespace}"')
    isolated = None
    try:
        isolated = create_engine(engine.url, connect_args={"connect_timeout": 5, "options": f"-c search_path={namespace}"})
        Base.metadata.create_all(isolated)
        sessions = sessionmaker(bind=isolated)
        settings = Settings(ingestion_runner="worker", ingestion_storage_dir=tmp_path / "uploads")
        services = Services()
        with sessions.begin() as db:
            db.add(User(email="e3@isolated.test", role="admin", password_hash=hash_password("isolated test password")))

        def override_db():
            with sessions() as db:
                yield db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_settings] = lambda: settings
        with TestClient(app) as client, httpx.Client(transport=httpx.MockTransport(services.handle)) as services_client:
            token = client.post("/api/v1/auth/login", json={"email": "e3@isolated.test", "password": "isolated test password"}).json()["access_token"]
            headers = {"Authorization": "Bearer " + token}
            first = client.post("/api/v1/ingestion/files", headers=headers,
                                files={"file": ("guide.md", b"Sardars describes a bathroom guide.")})
            assert first.status_code == 202
            first_id = first.json()["job_id"]
            with sessions() as db:
                assert db.get(IngestionJob, first_id).status == "pending"
                assert db.scalar(select(SourceRegistration)) is None
            old_run = claim(sessions, first_id, settings.import_timeout_seconds)
            with sessions.begin() as db:
                db.get(IngestionJob, first_id).lease_expires_at = now()
            assert process_one(sessions, settings, services_client)
            with sessions() as db:
                job = db.get(IngestionJob, first_id)
                source = db.scalar(select(SourceRegistration))
                assert job.status == "completed" and job.attempts == 2 and job.run_token != old_run.token
                assert source.is_active and source.index_status == "ready"
                source_id = source.source_id
                source_url = source.url
            updated = client.post("/api/v1/ingestion/files", headers=headers, data={"source_id": source_id},
                                  files={"file": ("guide.md", b"Sardars describes an updated bathroom guide.")})
            assert updated.status_code == 202
            assert process_one(sessions, settings, services_client)
            assert client.get(source_url, headers=headers).content == b"Sardars describes an updated bathroom guide."
            removed = client.delete("/api/v1/ingestion/sources/" + source_id, headers=headers)
            assert removed.status_code == 202
            assert client.get(source_url, headers=headers).status_code == 404
            assert process_one(sessions, settings, services_client)
            with sessions() as db:
                assert db.get(IngestionJob, removed.json()["job_id"]).status == "completed"
                assert not db.get(SourceRegistration, source_id).is_active
            assert services.points == {}
    finally:
        app.dependency_overrides.clear()
        if isolated is not None:
            isolated.dispose()
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{namespace}" CASCADE')
