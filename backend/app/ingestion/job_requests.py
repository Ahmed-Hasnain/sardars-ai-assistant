"""Bounded, reproducible public-site job snapshots and generation chunk IDs."""

from hashlib import sha256
import json
from typing import Literal, Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ingestion.prepare_site import prepare_chunks
from app.ingestion.public_site import source_type
from app.ingestion.site_documents import WebsiteDocument
from app.ingestion.documents import SuppliedDocument, file_url, valid_source, valid_web_url
from app.schemas.ingestion import SitemapSubmission

MAX_JOB_BYTES = 3 * 1024 * 1024


class StagedSource(BaseModel):
    """A bounded, durable reference; extraction happens in the worker."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    url: str = Field(min_length=1, max_length=2048)
    source_type: Literal["pdf", "text", "markdown", "web", "pages", "articles", "products"]
    visibility: Literal["public", "staff", "admin"]
    title: str = Field(min_length=1, max_length=500)
    original_filename: str = Field(min_length=1, max_length=200)
    media_type: Literal["application/pdf", "text/plain", "text/markdown", "text/html"]
    storage_key: UUID | None = None
    file_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def check_staging(self) -> Self:
        is_file = file_url(self.url)
        if (not valid_source(self.url, self.source_type)
            or any(ord(char) < 32 for char in self.title + self.original_filename)
            or "/" in self.original_filename or "\\" in self.original_filename
            or (is_file and (self.storage_key is None or self.file_sha256 is None))
            or (not is_file and (self.storage_key is not None or self.file_sha256 is not None))):
            raise ValueError("Invalid staged source")
        expected = {"pdf": "application/pdf", "text": "text/plain", "markdown": "text/markdown"}.get(self.source_type, "text/html")
        if self.media_type != expected:
            raise ValueError("Staged source format does not match media type")
        return self


class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["import", "remove", "crawl"]
    scope: Literal["public_site", "internal"] = "public_site"
    documents: list[WebsiteDocument | SuppliedDocument] = Field(default_factory=list, max_length=10)
    urls: list[str] = Field(default_factory=list, max_length=10)
    staged: StagedSource | None = None
    crawl: SitemapSubmission | None = None

    @model_validator(mode="after")
    def check_request(self) -> Self:
        if self.operation == "crawl":
            if self.scope != "internal" or self.crawl is None or self.documents or self.urls or self.staged:
                raise ValueError("Crawl requires only a bounded internal sitemap reference")
            urls = []
        elif self.operation == "import":
            if self.crawl is not None or bool(self.documents) == bool(self.staged) or self.urls:
                raise ValueError("Import requires either document snapshots or one staged source")
            if self.staged and self.scope != "internal":
                raise ValueError("Only internal imports may stage a source")
            urls = [self.staged.url] if self.staged else [document.url for document in self.documents]
        else:
            if not self.urls or self.documents or self.staged or self.crawl is not None:
                raise ValueError("Removal requires explicit URLs only")
            urls = self.urls
        if self.scope == "public_site" and any(not isinstance(doc, WebsiteDocument) for doc in self.documents):
            raise ValueError("Local public-site imports require crawler documents")
        if self.scope == "internal" and any(not isinstance(doc, SuppliedDocument) for doc in self.documents):
            raise ValueError("Internal imports require supplied document provenance")
        invalid_url = any(len(url) > 2048 or (source_type(url) is None if self.scope == "public_site" else not (valid_web_url(url) or file_url(url))) for url in urls)
        if len(set(urls)) != len(urls) or invalid_url:
            raise ValueError("Select unique owner-authorized descriptive Sardars URLs")
        return self

    def snapshot(self) -> dict:
        value = self.model_dump(mode="json")
        if value["staged"] is None:
            # Keep saved pre-E3 job snapshots byte-for-byte compatible with
            # idempotent CLI replay using an existing job ID.
            del value["staged"]
        if value["crawl"] is None:
            del value["crawl"]
        if len(json.dumps(value, ensure_ascii=False).encode()) > MAX_JOB_BYTES:
            raise ValueError("Job snapshot exceeds the size limit")
        return value

    def source_urls(self) -> list[str]:
        if self.operation == "remove":
            return self.urls
        if self.operation == "crawl":
            return []
        return [self.staged.url] if self.staged else [document.url for document in self.documents]


def source_id(url: str) -> str:
    return sha256(url.encode()).hexdigest()


def generation_chunks(document: WebsiteDocument | SuppliedDocument, generation: str | None) -> list[dict]:
    chunks = prepare_chunks([document])
    if generation is not None:
        for chunk in chunks:
            chunk["id"] = str(uuid5(NAMESPACE_URL, f"{document.source_id}:{generation}:{chunk['chunk_index']}"))
            chunk["index_generation"] = generation
    return chunks
