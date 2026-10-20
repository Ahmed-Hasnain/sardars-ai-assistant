"""Identity and integrity rules for authenticated, locally retained sources."""

from hashlib import sha256
import re
from typing import Literal, Self
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.ingestion.site_documents import MAX_DOCUMENT_CHARS, MAX_DOCUMENT_WORDS
from app.ingestion.public_site import source_type

FILE_PREFIX = "/api/v1/ingestion/files/"
FILE_TYPES = {"pdf", "text", "markdown"}


def valid_web_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        return (len(url) <= 2048 and parsed.scheme == "https" and bool(parsed.hostname)
                and parsed.netloc == parsed.hostname and not parsed.query and not parsed.fragment
                and not any(ord(c) <= 32 or ord(c) >= 127 or c == "\\" for c in url))
    except ValueError:
        return False


def valid_sitemap_url(url: str) -> bool:
    """Allow only direct XML URLs and bounded Shopify numeric range queries."""
    try:
        parsed = urlsplit(url)
        base = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
        if (len(url) > 2048 or parsed.fragment or not parsed.path.lower().endswith(".xml")
            or not valid_web_url(base)):
            return False
        if not parsed.query:
            return True
        match = re.fullmatch(r"from=([0-9]{1,20})&to=([0-9]{1,20})", parsed.query)
        return match is not None and int(match[1]) <= int(match[2])
    except (TypeError, ValueError):
        return False


def file_url(url: str) -> bool:
    if not url.startswith(FILE_PREFIX):
        return False
    try:
        return url == FILE_PREFIX + str(UUID(url[len(FILE_PREFIX):]))
    except ValueError:
        return False


def valid_source(url: str, kind: str) -> bool:
    if not isinstance(kind, str):
        return False
    if kind in FILE_TYPES:
        return file_url(url)
    return (kind == "web" and valid_web_url(url)) or (kind in {"pages", "articles", "products"} and source_type(url) == kind)


class SuppliedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_type: Literal["pdf", "text", "markdown", "web", "pages", "articles", "products"]
    visibility: Literal["public", "staff", "admin"]
    review_status: Literal["pending"] = "pending"
    title: str = Field(min_length=1, max_length=500)
    url: str = Field(min_length=1, max_length=2048)
    fetched_at: AwareDatetime
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    text: str = Field(min_length=1, max_length=MAX_DOCUMENT_CHARS)
    storage_key: UUID
    original_filename: str = Field(min_length=1, max_length=200)
    media_type: Literal["application/pdf", "text/plain", "text/markdown", "text/html"]
    file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def integrity(self) -> Self:
        if (not valid_source(self.url, self.source_type) or sha256(self.url.encode()).hexdigest() != self.source_id
            or sha256(self.text.encode()).hexdigest() != self.content_sha256 or not self.text.strip()
            or not self.title.strip() or len(self.text.split()) > MAX_DOCUMENT_WORDS
            or any(ord(c) < 32 for c in self.title + self.original_filename)
            or "/" in self.original_filename or "\\" in self.original_filename):
            raise ValueError("Invalid supplied document identity or integrity")
        expected = {"pdf": "application/pdf", "text": "text/plain", "markdown": "text/markdown"}.get(self.source_type, "text/html")
        if self.media_type != expected:
            raise ValueError("Document format does not match media type")
        return self
