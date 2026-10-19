"""Bounded sitemap discovery fans out to existing per-URL ingestion jobs."""

from uuid import NAMESPACE_URL, uuid5
from urllib.parse import urlsplit

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.models import IngestionJob
from app.ingestion.access import actor
from app.ingestion.extraction import discover_sitemap
from app.ingestion.job_requests import JobRequest, StagedSource
from app.ingestion.job_store import JobRun, enqueue, now, require_run, transaction
from app.ingestion.public_site import source_type
from app.ingestion.documents import valid_web_url


def run_crawl(sessions: sessionmaker[Session], run: JobRun, settings: Settings) -> dict:
    spec = run.request.crawl
    if spec is None:
        raise ValueError("Missing sitemap reference")
    with transaction(sessions) as db:
        job = require_run(db, run)
        user = actor(db, job)
        if user.role != "admin":
            raise ValueError("Sitemap submitter must remain an admin")
        saved = job.result if isinstance(job.result, dict) and isinstance(job.result.get("urls"), list) else None
    if saved is None:
        discovered = discover_sitemap(spec.url, settings, spec.max_pages)
        urls = discovered["urls"]
    else:
        urls = saved["urls"]
    sitemap_host = urlsplit(spec.url).hostname
    if (not urls or len(urls) > spec.max_pages or any(not isinstance(url, str) for url in urls)
        or len(set(urls)) != len(urls)
        or any(not valid_web_url(url) or urlsplit(url).hostname != sitemap_host
               or (sitemap_host == "sardarandco.com" and source_type(url) is None) for url in urls)):
        raise ValueError("Invalid discovered sitemap page set")
    if saved is None:
        with transaction(sessions) as db:
            job = require_run(db, run)
            user = actor(db, job)
            if user.role != "admin":
                raise ValueError("Sitemap submitter must remain an admin")
            job.result = {"urls": urls, "discovered_pages": len(urls),
                          "skipped_urls": discovered["skipped_urls"], "xml_files": discovered["xml_files"]}
    for url in urls:
        with transaction(sessions) as db:
            job = require_run(db, run)
            user = actor(db, job)
            if user.role != "admin":
                raise ValueError("Sitemap submitter must remain an admin")
            submitter_id = user.id
        staged = StagedSource(url=url, source_type=source_type(url) or "web", visibility=spec.visibility,
                              title="Pending sitemap page", original_filename="page.html", media_type="text/html")
        child_id = str(uuid5(NAMESPACE_URL, f"sitemap:{run.id}:{url}"))
        enqueue(sessions, JobRequest(operation="import", scope="internal", staged=staged),
                submitted_by_user_id=submitter_id, job_id=child_id, parent_job_id=run.id)
    with transaction(sessions) as db:
        job = require_run(db, run)
        user = actor(db, job)
        if user.role != "admin":
            raise ValueError("Sitemap submitter must remain an admin")
        job.status, job.finished_at = "completed", now()
        result = {key: value for key, value in job.result.items() if key != "urls"}
    return {"status": "completed", "operation": "crawl", **result, "indexed_chunks": 0,
            "skipped_chunks": 0, "deleted_chunks": 0}
