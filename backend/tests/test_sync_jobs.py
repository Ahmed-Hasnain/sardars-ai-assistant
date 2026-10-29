"""Durable synchronization lifecycle with isolated SQL and simulated Qdrant/Ollama."""

from datetime import timedelta
from hashlib import sha256
import json
from pathlib import Path

import httpx
from pydantic import ValidationError
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.db.base import Base
from app.db.models import IngestionJob, SourceRegistration
from app.ingestion.job_requests import JobRequest, generation_chunks
from app.ingestion.job_runner import JobFailed, run_job
from app.ingestion.job_store import claim, enqueue, fail, job_view, now, require_run
from app.ingestion.site_documents import WebsiteDocument
from app.ingestion.site_index import WebsiteIndexer
from app.ingestion.sync_sources import process, stage, preview
from app.retrieval.authorization import authorized_points
from app.retrieval.seed_config import DIMENSIONS

URL = "https://sardarandco.com/pages/about-us"


def document(words: int = 177, date: str = "2026-10-12T12:00:00+00:00", url: str = URL) -> WebsiteDocument:
    text = " ".join(f"testword{index}" for index in range(words))
    return WebsiteDocument.model_validate({
        "source_id": sha256(url.encode()).hexdigest(), "url": url, "source_type": "pages",
        "visibility": "public", "review_status": "pending", "title": "Isolated test document",
        "fetched_at": date, "text": text, "content_sha256": sha256(text.encode()).hexdigest(),
    })


class Services:
    def __init__(self):
        self.points = {}
        self.fail_path = None
        self.callback = None
        self.embeddings = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.callback:
            self.callback(request)
        if self.fail_path and request.url.path.endswith(self.fail_path):
            return httpx.Response(503, text="SECRET_UPSTREAM_DETAIL")
        if request.method == "GET":
            return httpx.Response(200, json={"result": {"config": {"params": {
                "vectors": {"size": DIMENSIONS, "distance": "Cosine"},
            }}}})
        body = json.loads(request.content)
        if request.url.path == "/api/embed":
            self.embeddings += len(body["input"])
            return httpx.Response(200, json={"embeddings": [[0.1] * DIMENSIONS for _ in body["input"]]})
        if request.url.path.endswith("/scroll"):
            conditions = body["filter"]["must"]
            rows = sorted((point for point in self.points.values() if all(
                point["payload"].get(condition["key"]) == condition["match"]["value"] for condition in conditions
            )), key=lambda point: str(point["id"]))
            if "offset" in body:
                rows = [point for point in rows if str(point["id"]) >= str(body["offset"])]
            selected = rows[:body["limit"]]
            offset = rows[body["limit"]]["id"] if len(rows) > body["limit"] else None
            selected = [dict(point) if body["with_payload"] else {"id": point["id"]} for point in selected]
            return httpx.Response(200, json={"status": "ok", "result": {"points": selected, "next_page_offset": offset}})
        if request.url.path.endswith("/delete"):
            assert request.url.params["wait"] == "true"
            for point_id in body["points"]:
                self.points.pop(point_id, None)
        else:
            assert request.method == "PUT" and request.url.params["wait"] == "true"
            self.points.update({point["id"]: point for point in body["points"]})
        return httpx.Response(200, json={"status": "ok", "result": {"status": "completed"}})


@pytest.fixture
def runtime(tmp_path: Path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'sync.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    services = Services()
    settings = Settings(_env_file=None, db_user="test", db_name="test", db_password="test")
    with httpx.Client(transport=httpx.MockTransport(services.handle)) as client:
        yield sessions, services, lambda: WebsiteIndexer(settings, client)
    engine.dispose()


def import_job(sessions, doc: WebsiteDocument) -> str:
    return enqueue(sessions, JobRequest(operation="import", documents=[doc]))


def test_update_shortens_document_and_old_evidence_is_hidden_before_network_calls(runtime) -> None:
    sessions, services, index = runtime
    original = document()
    initial = run_job(sessions, import_job(sessions, original), index())
    assert initial["indexed_chunks"] == 2
    old_ids = set(services.points)
    updated = document(32, "2026-10-13T12:00:00+00:00")
    seen = []

    def check_barrier(_request):
        with sessions() as db:
            source = db.get(SourceRegistration, original.source_id)
            assert source.index_status == "indexing"
            assert authorized_points(db, "staff", list(services.points.values())) == []
            assert authorized_points(db, "admin", list(services.points.values())) == []
            seen.append(True)

    services.callback = check_barrier
    result = run_job(sessions, import_job(sessions, updated), index())
    services.callback = None
    assert seen and result["updated_sources"] == 1 and result["deleted_chunks"] == 2
    assert len(services.points) == 1 and not (old_ids & services.points.keys())
    with sessions() as db:
        source = db.get(SourceRegistration, original.source_id)
        assert source.index_status == "ready" and source.content_sha256 == updated.content_sha256
        assert source.last_indexed_at and source.last_synced_at
        assert len(authorized_points(db, "staff", list(services.points.values()))) == 1


def test_unchanged_run_skips_embeddings_and_cleans_late_orphan_generation(runtime) -> None:
    sessions, services, index = runtime
    doc = document()
    run_job(sessions, import_job(sessions, doc), index())
    calls = services.embeddings
    point = next(iter(services.points.values()))
    services.points["orphan"] = {**point, "id": "orphan", "payload": {**point["payload"], "index_generation": "older-run"}}
    result = run_job(sessions, import_job(sessions, doc), index())
    assert result["indexed_chunks"] == 0 and result["skipped_chunks"] == 2
    assert result["deleted_chunks"] == 1 and len(services.points) == 2
    assert services.embeddings == calls


def test_failed_cleanup_is_persisted_and_retry_uses_original_snapshot(runtime) -> None:
    sessions, services, index = runtime
    run_job(sessions, import_job(sessions, document()), index())
    target = document(32, "2026-10-13T12:00:00+00:00")
    job_id = import_job(sessions, target)
    services.fail_path = "/delete"
    with pytest.raises(JobFailed):
        run_job(sessions, job_id, index())
    failed_points = dict(services.points)
    with sessions() as db:
        job = db.get(IngestionJob, job_id)
        assert job.status == "failed" and job.attempts == 1 and job.error_code == "index_error"
        assert "SECRET" not in job.error_message
        assert db.get(SourceRegistration, target.source_id).index_status == "failed"
        assert authorized_points(db, "staff", list(services.points.values())) == []
        assert job.request["documents"][0]["content_sha256"] == target.content_sha256
    services.fail_path = None
    result = run_job(sessions, job_id, index(), retry=True)
    assert result["attempts"] == 2 and len(services.points) == 1
    with sessions() as db:
        assert db.get(IngestionJob, job_id).status == "completed"
        assert authorized_points(db, "staff", list(services.points.values()))
        # Even the same content checksum cannot authorize an older run generation.
        old = [point for point in failed_points.values() if point["payload"]["content_sha256"] == target.content_sha256]
        assert old and authorized_points(db, "staff", old) == []


def test_removal_disables_before_cleanup_and_retry_never_reactivates(runtime) -> None:
    sessions, services, index = runtime
    doc = document()
    run_job(sessions, import_job(sessions, doc), index())
    job_id = enqueue(sessions, JobRequest(operation="remove", urls=[URL]))

    def check_removed(_request):
        with sessions() as db:
            source = db.get(SourceRegistration, doc.source_id)
            assert not source.is_active and source.index_status == "removed"
            assert authorized_points(db, "staff", list(services.points.values())) == []

    services.callback, services.fail_path = check_removed, "/delete"
    with pytest.raises(JobFailed):
        run_job(sessions, job_id, index())
    services.fail_path = None
    result = run_job(sessions, job_id, index(), retry=True)
    services.callback = None
    assert result["removed_sources"] == 1 and result["deleted_chunks"] == 2 and not services.points
    repeated = run_job(sessions, enqueue(sessions, JobRequest(operation="remove", urls=[URL])), index())
    assert repeated["deleted_chunks"] == 0
    with pytest.raises(JobFailed, match="disabled"):
        run_job(sessions, import_job(sessions, doc), index())
    with sessions() as db:
        assert not db.get(SourceRegistration, doc.source_id).is_active


def test_orphan_cleanup_for_unregistered_url_does_not_invent_registration(runtime) -> None:
    sessions, services, index = runtime
    doc = document()
    services.points["orphan"] = {"id": "orphan", "payload": {"source_id": doc.source_id}}
    result = run_job(sessions, enqueue(sessions, JobRequest(operation="remove", urls=[URL])), index())
    assert result["deleted_chunks"] == 1 and not services.points
    with sessions() as db:
        assert db.get(SourceRegistration, doc.source_id) is None


def test_expired_worker_is_fenced_and_late_vectors_are_not_authorized(runtime) -> None:
    sessions, services, index = runtime
    doc = document()
    job_id = import_job(sessions, doc)
    old_run = claim(sessions, job_id, 300)
    stage(sessions, old_run, index())
    with sessions.begin() as db:
        db.get(IngestionJob, job_id).lease_expires_at = now() - timedelta(seconds=1)
    new_run = claim(sessions, job_id, 300, retry=True)
    assert old_run.token != new_run.token
    process(sessions, new_run, index())
    with sessions.begin() as db, pytest.raises(ValueError, match="ownership"):
        require_run(db, old_run)
    fail(sessions, old_run, "late", "Old worker failure")
    # A late physical writer has different point IDs and cannot overwrite publication.
    index().upsert_chunks(generation_chunks(doc, old_run.token), {doc.source_id: "owner_authorized_site_for_internal_use"})
    with sessions() as db:
        assert db.get(IngestionJob, job_id).status == "completed"
        eligible = authorized_points(db, "staff", list(services.points.values()))
        assert len(eligible) == 2
        assert all(point["payload"]["index_generation"] == new_run.token for point in eligible)


def test_live_job_claim_and_source_ownership_prevent_concurrent_overwrite(runtime) -> None:
    sessions, _services, index = runtime
    doc = document()
    job_id = import_job(sessions, doc)
    active = claim(sessions, job_id, 300)
    stage(sessions, active, index())
    with pytest.raises(ValueError, match="cannot be claimed"):
        claim(sessions, job_id, 300, retry=True)
    other = import_job(sessions, doc)
    with pytest.raises(JobFailed, match="another job"):
        run_job(sessions, other, index())
    with sessions() as db:
        assert db.get(SourceRegistration, doc.source_id).index_job_id == active.id
        assert db.get(SourceRegistration, doc.source_id).index_status == "indexing"


def test_retries_are_limited_and_newer_source_blocks_an_old_snapshot(runtime) -> None:
    sessions, services, index = runtime
    old = document()
    job_id = import_job(sessions, old)
    services.fail_path = "/api/embed"
    for attempt in range(3):
        with pytest.raises(JobFailed):
            run_job(sessions, job_id, index(), retry=bool(attempt))
    with pytest.raises(ValueError, match="limit"):
        run_job(sessions, job_id, index(), retry=True)
    with sessions() as db:
        assert db.get(IngestionJob, job_id).attempts == 3
    services.fail_path = None
    run_job(sessions, import_job(sessions, document(32, "2026-10-13T12:00:00+00:00")), index())
    with pytest.raises(JobFailed, match="older"):
        run_job(sessions, import_job(sessions, old), index())


@pytest.mark.parametrize("visibility", ["admin", "staff"])
def test_public_workflow_cannot_change_or_remove_restricted_registration(runtime, visibility: str) -> None:
    sessions, _services, index = runtime
    doc = document()
    with sessions.begin() as db:
        db.add(SourceRegistration(source_id=doc.source_id, url=URL, source_type="pages", visibility=visibility,
                                  content_sha256=doc.content_sha256, authorization_basis="private", is_active=True))
    for request in (JobRequest(operation="import", documents=[doc]), JobRequest(operation="remove", urls=[URL])):
        with pytest.raises(JobFailed, match="visibility"):
            run_job(sessions, enqueue(sessions, request), index())
    with sessions() as db:
        source = db.get(SourceRegistration, doc.source_id)
        assert source.visibility == visibility and source.is_active


def test_preview_and_job_view_do_not_publish_data_or_expose_snapshots(runtime) -> None:
    sessions, services, index = runtime
    request = JobRequest(operation="import", documents=[document()])
    with sessions() as db:
        assert preview(db, request)["status"] == "preview"
        assert not list(db.scalars(select(IngestionJob)))
    job_id = enqueue(sessions, request)
    with sessions() as db:
        visible = json.dumps(job_view(db.get(IngestionJob, job_id)))
        assert "testword" not in visible and "request" not in visible and "run_token" not in visible
    run_job(sessions, job_id, index())
    with pytest.raises(ValueError):
        run_job(sessions, job_id, index(), retry=True)
    assert len(services.points) == 2


@pytest.mark.parametrize("value", [
    {"operation": "remove", "urls": ["https://other.example/pages/about-us"]},
    {"operation": "remove", "urls": [URL, URL]}, {"operation": "remove", "urls": [URL] * 11},
    {"operation": "import"}, {"operation": "remove", "urls": []},
    {"operation": "execute_sql", "urls": [URL]},
])
def test_job_requests_are_narrow_validated_and_bounded(value: dict) -> None:
    with pytest.raises(ValidationError):
        JobRequest.model_validate(value)


def test_invalid_stored_snapshot_is_recorded_as_a_safe_failure(runtime) -> None:
    sessions, _services, index = runtime
    job_id = import_job(sessions, document())
    with sessions.begin() as db:
        db.get(IngestionJob, job_id).request = {"operation": "remove", "urls": ["SECRET_INVALID_URL"]}
    with pytest.raises(ValueError, match="Invalid stored"):
        run_job(sessions, job_id, index())
    with sessions() as db:
        job = db.get(IngestionJob, job_id)
        assert job.status == "failed" and job.error_code == "invalid_snapshot" and job.attempts == 1
        assert "SECRET" not in json.dumps(job_view(job))


def test_queued_old_job_cannot_overwrite_newer_publication_with_same_fetch_time(runtime) -> None:
    sessions, _services, index = runtime
    old_job = import_job(sessions, document(177))
    latest = document(32)  # Same fetched_at; job/publication ordering still matters.
    run_job(sessions, import_job(sessions, latest), index())
    with pytest.raises(JobFailed, match="after this job"):
        run_job(sessions, old_job, index())
    with sessions() as db:
        source = db.get(SourceRegistration, latest.source_id)
        assert source.index_status == "ready" and source.content_sha256 == latest.content_sha256


def test_permission_change_mid_update_prevents_publication(runtime) -> None:
    sessions, services, index = runtime
    doc = document()
    def disable(request):
        if request.method == "PUT":
            with sessions.begin() as db:
                db.get(SourceRegistration, doc.source_id).is_active = False
    services.callback = disable
    with pytest.raises(JobFailed, match="permissions"):
        run_job(sessions, import_job(sessions, doc), index())
    with sessions() as db:
        source = db.get(SourceRegistration, doc.source_id)
        assert not source.is_active and source.index_status == "failed"
        assert authorized_points(db, "staff", list(services.points.values())) == []
