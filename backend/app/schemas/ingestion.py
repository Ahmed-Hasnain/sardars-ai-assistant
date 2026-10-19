"""Strict public inputs; identity, provenance, and checksums are server supplied."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.ingestion.documents import valid_web_url


class URLSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=2048)
    visibility: Literal["public", "staff", "admin"] = "staff"

    @field_validator("url")
    @classmethod
    def check_url(cls, value: str) -> str:
        if not valid_web_url(value):
            raise ValueError("Use a direct HTTPS URL without credentials, query, or fragment")
        return value


class SitemapSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=2048)
    visibility: Literal["staff", "admin"] = "staff"
    max_pages: int = Field(default=1500, ge=1, le=1500)

    @field_validator("url")
    @classmethod
    def check_sitemap(cls, value: str) -> str:
        from urllib.parse import urlsplit

        if not valid_web_url(value) or not urlsplit(value).path.lower().endswith(".xml"):
            raise ValueError("Use a direct HTTPS sitemap XML URL without credentials, query, or fragment")
        return value


class FileSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    visibility: Literal["public", "staff", "admin"] = "staff"
    title: str | None = Field(default=None, min_length=1, max_length=500)
    source_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$", description="Existing uploaded source ID for a content update; leave blank for a new upload")

    @field_validator("title", "source_id", mode="before")
    @classmethod
    def blank_optional_fields(cls, value: object) -> object:
        # Browser multipart forms may send untouched optional inputs as empty
        # strings. Treat them like omitted fields; validate nonempty values.
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("title")
    @classmethod
    def check_title(cls, value: str | None) -> str | None:
        if value is not None and (not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ValueError("Invalid title")
        return value.strip() if value else value
