"""Turn a durable internal source reference into a fixed document snapshot."""

from dataclasses import replace
from hashlib import sha256
import time
from urllib.parse import urlsplit

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.ingestion.access import actor, check_submission
from app.ingestion.documents import SuppliedDocument, file_url
from app.ingestion.extraction import ExtractionError, extract_file, extract_url, storage_path, store_original
from app.ingestion.extract_worker import MAX_FILE_BYTES
from app.ingestion.job_requests import JobRequest, source_id
from app.ingestion.job_store import JobRun, now, require_run, transaction
from app.ingestion.sync_sources import can_restore, source_record

MIN_SITEMAP_PAGE_DELAY_SECONDS = 0.5


def materialize(sessions: sessionmaker[Session], run: JobRun, settings: Settings) -> JobRun:
    staged = run.request.staged
    if staged is None:
        return run
    with transaction(sessions) as db:
        job = require_run(db, run)
        user = actor(db, job)
        is_sitemap_page = job.parent_job_id is not None
        source = source_record(db, staged.url, lock=True, internal=True)
        check_submission(user, source, staged.visibility)
        if source and source.source_type != staged.source_type:
            raise ValueError("Source is disabled or its format changed")
        if run.request.restore_removed:
            if user.role != "admin" or not can_restore(db, source, run.id):
                raise ValueError("Removed source cannot be restored by this job")
        elif source and not source.is_active:
            raise ValueError("Source is disabled or its format changed")

    created_key = None
    if file_url(staged.url):
        path = storage_path(settings, str(staged.storage_key))
        try:
            with path.open("rb") as stream:
                raw = stream.read(MAX_FILE_BYTES + 1)
        except OSError as exc:
            raise ExtractionError("Stored original is unavailable") from exc
        if len(raw) > MAX_FILE_BYTES or sha256(raw).hexdigest() != staged.file_sha256:
            raise ExtractionError("Stored original failed integrity check")
        title = staged.title
        text = extract_file(raw, staged.source_type)
        key, checksum = str(staged.storage_key), staged.file_sha256
    else:
        if urlsplit(staged.url).hostname not in settings.ingestion_url_hosts:
            raise ValueError("URL host is no longer configured for ingestion")
        if is_sitemap_page:
            time.sleep(MIN_SITEMAP_PAGE_DELAY_SECONDS)
        raw, title, text = extract_url(staged.url, settings)
        key, checksum = store_original(settings, raw)
        created_key = key

    try:
        document = SuppliedDocument(
            source_id=source_id(staged.url), url=staged.url, source_type=staged.source_type,
            visibility=staged.visibility, title=title, text=text, fetched_at=now(),
            content_sha256=sha256(text.encode()).hexdigest(), storage_key=key,
            original_filename=staged.original_filename, media_type=staged.media_type,
            file_sha256=checksum,
        )
        request = JobRequest(operation="import", scope="internal", documents=[document],
                             restore_removed=run.request.restore_removed)
        with transaction(sessions) as db:
            job = require_run(db, run)
            user = actor(db, job)
            source = source_record(db, staged.url, lock=True, internal=True)
            check_submission(user, source, staged.visibility)
            if source and source.source_type != staged.source_type:
                raise ValueError("Source is disabled or its format changed")
            if run.request.restore_removed:
                if user.role != "admin" or not can_restore(db, source, run.id):
                    raise ValueError("Removed source cannot be restored by this job")
            elif source and not source.is_active:
                raise ValueError("Source is disabled or its format changed")
            job.request = request.snapshot()
    except Exception:
        if created_key is not None:
            storage_path(settings, created_key).unlink(missing_ok=True)
        raise
    return replace(run, request=request)
