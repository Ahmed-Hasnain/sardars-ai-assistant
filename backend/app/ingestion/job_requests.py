"""Bounded, reproducible public-site job snapshots and generation chunk IDs."""

from hashlib import sha256
import json
from typing import Literal, Self
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ingestion.prepare_site import prepare_chunks
from app.ingestion.public_site import source_type
from app.ingestion.site_documents import WebsiteDocument
from app.ingestion.documents import SuppliedDocument, file_url, valid_web_url

MAX_JOB_BYTES = 3 * 1024 * 1024


class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["import", "remove"]
    scope: Literal["public_site", "internal"] = "public_site"
    documents: list[WebsiteDocument | SuppliedDocument] = Field(default_factory=list, max_length=10)
    urls: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def check_request(self) -> Self:
        if self.operation == "import":
            if not self.documents or self.urls:
                raise ValueError("Import requires document snapshots only")
            urls = [document.url for document in self.documents]
        else:
            if not self.urls or self.documents:
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
        if len(json.dumps(value, ensure_ascii=False).encode()) > MAX_JOB_BYTES:
            raise ValueError("Job snapshot exceeds the size limit")
        return value

    def source_urls(self) -> list[str]:
        return self.urls if self.operation == "remove" else [document.url for document in self.documents]


def source_id(url: str) -> str:
    return sha256(url.encode()).hexdigest()


def generation_chunks(document: WebsiteDocument | SuppliedDocument, generation: str | None) -> list[dict]:
    chunks = prepare_chunks([document])
    if generation is not None:
        for chunk in chunks:
            chunk["id"] = str(uuid5(NAMESPACE_URL, f"{document.source_id}:{generation}:{chunk['chunk_index']}"))
            chunk["index_generation"] = generation
    return chunks
