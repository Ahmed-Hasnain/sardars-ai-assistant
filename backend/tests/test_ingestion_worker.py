"""Background admission and recovery without changing the E1 corpus."""

from datetime import timedelta
import httpx
from sqlalchemy import select

from app.db.models import IngestionJob, SourceRegistration, User
from app.ingestion.job_requests import JobRequest
from app.ingestion.job_store import claim, now
from app.ingestion.worker import process_one
from test_ingestion_api import runtime, upload


def run_once(sessions, settings, services):
    with httpx.Client(transport=httpx.MockTransport(services.handle)) as client:
        return process_one(sessions, settings, client)


def test_legacy_job_snapshot_stays_compatible():
    request = JobRequest(operation="remove", urls=["https://sardarandco.com/pages/about-us"])
    assert "staged" not in request.snapshot()


def test_file_is_queued_without_extraction_then_published_by_worker(runtime):
    client, sessions, settings, services, headers = runtime
    settings.ingestion_runner = "worker"
    response = upload(client, headers["staff"])
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    with sessions() as db:
        job = db.get(IngestionJob, job_id)
        assert job.status == "pending" and job.attempts == 0
        assert job.request["staged"]["storage_key"]
        assert job.request["documents"] == []
        assert db.scalar(select(SourceRegistration)) is None
    assert run_once(sessions, settings, services)
    with sessions() as db:
        job = db.get(IngestionJob, job_id)
        source = db.scalar(select(SourceRegistration))
        assert job.status == "completed" and job.attempts == 1
        assert "staged" not in job.request and job.request["documents"]
        assert source.index_status == "ready" and source.visibility == "staff"
        assert source.storage_key == job.request["documents"][0]["storage_key"]
    assert len(services.points) == 1
    assert not run_once(sessions, settings, services)


def test_queued_jobs_run_serially_and_retry_the_fixed_snapshot(runtime):
    client, sessions, settings, services, headers = runtime
    settings.ingestion_runner = "worker"
    first = upload(client, headers["staff"])
    second = upload(client, headers["admin"], b"Sardars describes a second bathroom item.")
    assert first.status_code == second.status_code == 202
    assert run_once(sessions, settings, services)
    with sessions() as db:
        assert db.get(IngestionJob, second.json()["job_id"]).status == "pending"
    services.fail_path = "/api/embed"
    assert run_once(sessions, settings, services)
    job_id = second.json()["job_id"]
    with sessions() as db:
        job = db.get(IngestionJob, job_id)
        assert job.status == "failed" and job.attempts == 1
        assert job.request["documents"]
    assert client.post(f"/api/v1/ingestion/jobs/{job_id}/retry", headers=headers["staff"]).status_code == 404
    services.fail_path = None
    retried = client.post(f"/api/v1/ingestion/jobs/{job_id}/retry", headers=headers["admin"])
    assert retried.status_code == 202 and retried.json()["status"] == "pending"
    assert run_once(sessions, settings, services)
    with sessions() as db:
        assert db.get(IngestionJob, job_id).status == "completed"
        assert db.get(IngestionJob, job_id).attempts == 2


def test_revoked_submitter_cannot_publish_and_removal_hides_before_cleanup(runtime):
    client, sessions, settings, services, headers = runtime
    settings.ingestion_runner = "worker"
    pending = upload(client, headers["staff"])
    with sessions.begin() as db:
        db.scalar(select(User).where(User.email == "staff@test.local")).is_active = False
    assert run_once(sessions, settings, services)
    with sessions() as db:
        assert db.get(IngestionJob, pending.json()["job_id"]).status == "failed"
        assert db.scalar(select(SourceRegistration)) is None
    assert services.points == {}

    published = upload(client, headers["admin"])
    assert run_once(sessions, settings, services)
    with sessions() as db:
        source = db.scalar(select(SourceRegistration))
        identity = source.source_id
        file_url = source.url
        assert source.is_active
    removed = client.delete(f"/api/v1/ingestion/sources/{identity}", headers=headers["admin"])
    assert removed.status_code == 202
    with sessions() as db:
        assert not db.get(SourceRegistration, identity).is_active
    assert client.get(file_url, headers=headers["admin"]).status_code == 404
    assert run_once(sessions, settings, services)
    assert services.points == {}


def test_expired_lease_is_recovered_and_fenced(runtime):
    client, sessions, settings, services, headers = runtime
    settings.ingestion_runner = "worker"
    job_id = upload(client, headers["staff"]).json()["job_id"]
    old_run = claim(sessions, job_id, settings.import_timeout_seconds)
    with sessions.begin() as db:
        db.get(IngestionJob, job_id).lease_expires_at = now() - timedelta(seconds=1)
    assert run_once(sessions, settings, services)
    with sessions() as db:
        job = db.get(IngestionJob, job_id)
        assert job.status == "completed" and job.attempts == 2
        assert job.run_token != old_run.token


def test_url_fetch_happens_in_worker_and_source_is_queued_without_text(runtime, monkeypatch):
    client, sessions, settings, services, headers = runtime
    settings.ingestion_runner = "worker"
    fetched = []

    def extract(url, _settings):
        fetched.append(url)
        return b"<html><main>Bathroom guide.</main></html>", "Bathroom guide", "Sardars describes a bathroom guide."

    monkeypatch.setattr("app.ingestion.materialize.extract_url", extract)
    url = "https://sardarandco.com/pages/e3-worker-sample"
    response = client.post("/api/v1/ingestion/urls", headers=headers["admin"], json={"url": url})
    assert response.status_code == 202 and fetched == []
    with sessions() as db:
        job = db.get(IngestionJob, response.json()["job_id"])
        assert job.request["staged"]["url"] == url and job.request["documents"] == []
    assert run_once(sessions, settings, services) and fetched == [url]
    with sessions() as db:
        source = db.scalar(select(SourceRegistration).where(SourceRegistration.url == url))
        assert source.index_status == "ready" and source.storage_key


def test_removed_page_requires_explicit_admin_restore_and_keeps_identity(runtime, monkeypatch):
    client, sessions, settings, services, headers = runtime
    settings.ingestion_runner = "worker"
    url = "https://sardarandco.com/pages/about-us"
    monkeypatch.setattr("app.ingestion.materialize.extract_url", lambda *_args: (
        b"<html><main>About Sardars</main></html>", "About Sardars", "Sardars describes bathroom products."
    ))
    created = client.post("/api/v1/ingestion/urls", headers=headers["admin"], json={"url": url})
    assert created.status_code == 202
    assert run_once(sessions, settings, services)
    with sessions() as db:
        source = db.scalar(select(SourceRegistration).where(SourceRegistration.url == url))
        identity = source.source_id
        assert source.is_active and source.index_status == "ready"
    assert services.points

    removed = client.delete(f"/api/v1/ingestion/sources/{identity}", headers=headers["admin"])
    assert removed.status_code == 202
    assert client.post(f"/api/v1/ingestion/sources/{identity}/restore", headers=headers["admin"]).status_code == 409
    assert run_once(sessions, settings, services)
    assert not services.points
    assert client.post("/api/v1/ingestion/urls", headers=headers["admin"], json={"url": url}).status_code == 409
    assert client.post(f"/api/v1/ingestion/sources/{identity}/restore", headers=headers["staff"]).status_code == 403

    restored = client.post(f"/api/v1/ingestion/sources/{identity}/restore", headers=headers["admin"])
    assert restored.status_code == 202
    with sessions() as db:
        source = db.get(SourceRegistration, identity)
        job = db.get(IngestionJob, restored.json()["job_id"])
        assert not source.is_active and source.index_status == "removed"
        assert job.request["restore_removed"] is True and job.request["staged"]["url"] == url
    assert run_once(sessions, settings, services)
    with sessions() as db:
        source = db.get(SourceRegistration, identity)
        job = db.get(IngestionJob, restored.json()["job_id"])
        assert source.is_active and source.index_status == "ready" and source.index_job_id == job.id
        assert job.status == "completed" and job.result["restored_sources"] == 1
    assert len(services.points) == 1


def test_failed_page_restore_stays_hidden_and_can_retry(runtime, monkeypatch):
    client, sessions, settings, services, headers = runtime
    settings.ingestion_runner = "worker"
    url = "https://sardarandco.com/pages/about-us"
    monkeypatch.setattr("app.ingestion.materialize.extract_url", lambda *_args: (
        b"<html><main>About Sardars</main></html>", "About Sardars", "Sardars describes bathroom products."
    ))
    assert client.post("/api/v1/ingestion/urls", headers=headers["admin"], json={"url": url}).status_code == 202
    assert run_once(sessions, settings, services)
    with sessions() as db:
        identity = db.scalar(select(SourceRegistration).where(SourceRegistration.url == url)).source_id
    assert client.delete(f"/api/v1/ingestion/sources/{identity}", headers=headers["admin"]).status_code == 202
    assert run_once(sessions, settings, services)
    restored = client.post(f"/api/v1/ingestion/sources/{identity}/restore", headers=headers["admin"])
    job_id = restored.json()["job_id"]
    services.fail_path = "/api/embed"
    assert run_once(sessions, settings, services)
    with sessions() as db:
        source = db.get(SourceRegistration, identity)
        assert not source.is_active and source.index_status == "failed"
        assert db.get(IngestionJob, job_id).status == "failed"
    services.fail_path = None
    assert client.post(f"/api/v1/ingestion/jobs/{job_id}/retry", headers=headers["admin"]).status_code == 202
    assert run_once(sessions, settings, services)
    with sessions() as db:
        source = db.get(SourceRegistration, identity)
        assert source.is_active and source.index_status == "ready"
        assert db.get(IngestionJob, job_id).status == "completed"


def test_restore_waits_for_failed_removal_cleanup(runtime, monkeypatch):
    client, sessions, settings, services, headers = runtime
    settings.ingestion_runner = "worker"
    url = "https://sardarandco.com/pages/about-us"
    monkeypatch.setattr("app.ingestion.materialize.extract_url", lambda *_args: (
        b"<html><main>About Sardars</main></html>", "About Sardars", "Sardars describes bathroom products."
    ))
    assert client.post("/api/v1/ingestion/urls", headers=headers["admin"], json={"url": url}).status_code == 202
    assert run_once(sessions, settings, services)
    with sessions() as db:
        identity = db.scalar(select(SourceRegistration).where(SourceRegistration.url == url)).source_id
    removal = client.delete(f"/api/v1/ingestion/sources/{identity}", headers=headers["admin"])
    removal_id = removal.json()["job_id"]
    services.fail_path = "/delete"
    assert run_once(sessions, settings, services)
    with sessions() as db:
        source = db.get(SourceRegistration, identity)
        assert not source.is_active and source.index_status == "removed"
        assert db.get(IngestionJob, removal_id).status == "failed"
    assert client.post(f"/api/v1/ingestion/sources/{identity}/restore", headers=headers["admin"]).status_code == 409
    services.fail_path = None
    assert client.post(f"/api/v1/ingestion/jobs/{removal_id}/retry", headers=headers["admin"]).status_code == 202
    assert run_once(sessions, settings, services)
    assert client.post(f"/api/v1/ingestion/sources/{identity}/restore", headers=headers["admin"]).status_code == 202
