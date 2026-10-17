import re
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field, field_validator

from app.schemas.ask import SourceCitation


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    product_handles: list[str] = Field(default_factory=list, max_length=3)

    @field_validator("message")
    @classmethod
    def strip_message(cls, value: str) -> str:
        message = value.strip()
        if not message:
            raise ValueError("Message cannot be empty")
        return message

    @field_validator("product_handles")
    @classmethod
    def validate_product_handles(cls, values: list[str]) -> list[str]:
        if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}", value) for value in values):
            raise ValueError("Invalid product handle")
        return values


class ProductSource(BaseModel):
    source_file_sha256: str
    database_observed_at: AwareDatetime
    source_exported_at: AwareDatetime | None
    imported_at: AwareDatetime
    currency: str | None
    authority: Literal["developer_authorized_products_table"] = "developer_authorized_products_table"
    database_values_verified: Literal[True] = True
    current_price_verified: Literal[True] = True
    external_sync_verified: Literal[False] = False


class MatchedProduct(BaseModel):
    handle: str
    title: str
    sku: str
    price: str
    currency: str | None
    database_observed_at: AwareDatetime
    source_file_sha256: str
    variant_count: int
    specifications: dict[str, str] = Field(default_factory=dict)
    description_source_id: str | None = None


class ChatResponse(BaseModel):
    answer: str
    route: Literal["general", "company", "product", "product_search"]
    sources: list[SourceCitation] = Field(default_factory=list)
    model: str | None
    company_data_verified: bool = False
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    duration_ms: float | None = None
    product_source: ProductSource | None = None
    products: list[MatchedProduct] = Field(default_factory=list)
    product_handles: list[str] = Field(default_factory=list)
