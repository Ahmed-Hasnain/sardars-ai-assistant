"""Validate saved public-site extraction records before preparing an import.

Validation checks record integrity, not factual accuracy or source permissions.
The extractor's legacy ``pending`` label does not create an approval queue.
"""

from datetime import datetime
from hashlib import sha256
from typing import Literal, Self

from pydantic import (
    AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator,
)

from app.ingestion.public_site import source_type


MAX_DOCUMENT_CHARS = 50_000
MAX_DOCUMENT_WORDS = 10_000


class DescriptiveDerivation(BaseModel):
    """Link an exact excerpt to its retained original crawler snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    method: Literal["descriptive_spans_v1"]
    original_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class WebsiteDocument(BaseModel):
    """The current crawler format; preserve exact text for checksum comparison."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_type: Literal["pages", "articles", "products"]
    visibility: Literal["public"]
    review_status: Literal["pending"]
    title: str = Field(min_length=1, max_length=500)
    url: str = Field(min_length=1, max_length=2048)
    fetched_at: AwareDatetime
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    text: str = Field(min_length=1, max_length=MAX_DOCUMENT_CHARS)
    derivation: DescriptiveDerivation | None = None

    @field_validator("fetched_at", mode="before")
    @classmethod
    def parse_fetch_time(cls, value: object) -> datetime:
        if not isinstance(value, str):
            raise ValueError("Fetch time must be an ISO timestamp")
        return datetime.fromisoformat(value)

    @model_validator(mode="after")
    def check_integrity(self) -> Self:
        if source_type(self.url) != self.source_type:
            raise ValueError("Unsupported URL or mismatched source type")
        if sha256(self.url.encode()).hexdigest() != self.source_id:
            raise ValueError("Source ID must match the URL")
        if not self.title.strip() or not self.text.strip():
            raise ValueError("Title and text must not be blank")
        if len(self.text.split()) > MAX_DOCUMENT_WORDS:
            raise ValueError("Document exceeds the word limit")
        if sha256(self.text.encode()).hexdigest() != self.content_sha256:
            raise ValueError("Content checksum must match the exact extracted text")
        return self
