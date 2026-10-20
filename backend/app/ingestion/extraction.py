"""Bounded parser subprocess and safe local original-file storage."""

import base64
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import UUID, uuid4

from app.core.config import Settings
from app.ingestion.documents import valid_web_url
from app.ingestion.extract_worker import MAX_FILE_BYTES

FORMATS = {".txt": ("text", "text/plain"), ".md": ("markdown", "text/markdown"), ".pdf": ("pdf", "application/pdf")}


class ExtractionError(ValueError):
    pass


def run_extraction(request: dict) -> dict:
    # The parser needs import paths, not application/database credentials.
    environment = {"PYTHONPATH": str(Path(__file__).resolve().parents[2]), "LANG": "C.UTF-8"}
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "app.ingestion.extract_worker"],
            input=json.dumps(request).encode(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=30, env=environment, check=False,
        )
        if completed.returncode or len(completed.stdout) > 5 * 1024 * 1024:
            raise ExtractionError("Extraction exceeded a resource limit or failed")
        result = json.loads(completed.stdout)
        if "error" in result:
            raise ExtractionError(result["error"])
        return result
    except subprocess.TimeoutExpired as exc:
        raise ExtractionError("Extraction exceeded its 30-second time limit") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ExtractionError("Extraction service unavailable") from exc


def file_format(filename: str) -> tuple[str, str]:
    if (not filename or len(filename) > 200 or "/" in filename or "\\" in filename
        or any(ord(char) < 32 or ord(char) == 127 for char in filename)):
        raise ExtractionError("Use a simple filename of at most 200 characters")
    try:
        return FORMATS[Path(filename).suffix.lower()]
    except KeyError as exc:
        raise ExtractionError("Supported file formats are PDF, UTF-8 TXT, and Markdown") from exc


def extract_file(raw: bytes, kind: str) -> str:
    if not raw or len(raw) > MAX_FILE_BYTES:
        raise ExtractionError("File must contain between 1 byte and 5 MiB")
    return run_extraction({"mode": "file", "raw": base64.b64encode(raw).decode(), "kind": kind})["text"]


def extract_url(url: str, settings: Settings) -> tuple[bytes, str, str]:
    result = run_extraction({"mode": "url", "url": url, "hosts": settings.ingestion_url_hosts})
    return base64.b64decode(result["raw"], validate=True), result["title"], result["text"]


def discover_sitemap(url: str, settings: Settings, max_pages: int) -> dict:
    result = run_extraction({"mode": "sitemap", "url": url, "hosts": settings.ingestion_url_hosts,
                             "max_pages": max_pages})
    if (not isinstance(result.get("urls"), list) or len(result["urls"]) > max_pages
        or not all(isinstance(item, str) and valid_web_url(item) for item in result["urls"])):
        raise ExtractionError("Sitemap discovery returned invalid URLs")
    return result


def storage_path(settings: Settings, key: str) -> Path:
    key = str(UUID(key))
    return settings.ingestion_storage_dir.resolve() / (key + ".blob")


def store_original(settings: Settings, raw: bytes) -> tuple[str, str]:
    key = str(uuid4())
    path = storage_path(settings, key)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return key, sha256(raw).hexdigest()
