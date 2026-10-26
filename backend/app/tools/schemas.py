"""Strict inputs and bounded structured results for the first read tool."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ToolInvocation(StrictModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    arguments: dict[str, object]


class SourceStatusArguments(StrictModel):
    source_id: str = Field(pattern=r"^[0-9a-f]{64}$")


class SourceStatus(StrictModel):
    authority: Literal["application_source_registry"] = "application_source_registry"
    observed_at: AwareDatetime
    source_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    title: str | None = Field(max_length=500)
    url: str = Field(max_length=2048)
    visibility: Literal["public", "staff", "admin"]
    is_active: bool
    index_status: Literal["ready", "indexing", "failed", "removed"]
    retrieval_ready: bool
    fetched_at: AwareDatetime | None
    last_indexed_at: AwareDatetime | None
    last_synced_at: AwareDatetime | None
    company_facts_verified: Literal[False] = False


class ProductArguments(StrictModel):
    identifier: str | None = Field(default=None, min_length=1, max_length=200, pattern=r"^[^\s\x00-\x1f]+$")
    question: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def one_lookup(self) -> "ProductArguments":
        if (self.identifier is None) == (self.question is None):
            raise ValueError("Provide one lookup input")
        return self


class ProductVariant(StrictModel):
    source_row_number: int = Field(ge=1)
    row_kind: Literal["variant", "image_only"]
    sku: str | None = Field(max_length=200)
    option1_name: str | None = Field(max_length=200)
    option1_value: str | None = Field(max_length=200)
    option2_name: str | None = Field(max_length=200)
    option2_value: str | None = Field(max_length=200)
    option3_name: str | None = Field(max_length=200)
    option3_value: str | None = Field(max_length=200)
    price: str = Field(max_length=80)
    stock_quantity: int | None = Field(default=None, ge=0)


class ProductDetails(StrictModel):
    authority: Literal["developer_authorized_products_table"] = "developer_authorized_products_table"
    observed_at: AwareDatetime
    query_match: Literal["sku", "handle", "name"]
    handle: str = Field(max_length=200)
    title: str | None = Field(max_length=500)
    vendor: str | None = Field(max_length=200)
    category: str | None = Field(default=None, max_length=200)
    product_type: str | None = Field(default=None, max_length=200)
    source_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_exported_at: AwareDatetime | None
    imported_at: AwareDatetime
    currency: str | None = Field(max_length=3)
    database_values_verified: Literal[True] = True
    current_price_verified: Literal[True] = True
    external_sync_verified: Literal[False] = False
    inventory_verified: bool = False
    variants: list[ProductVariant] = Field(min_length=1, max_length=32)


class ProductCandidate(StrictModel):
    handle: str = Field(max_length=200)
    title: str | None = Field(max_length=500)


class ProductCandidates(StrictModel):
    authority: Literal["developer_authorized_products_table"] = "developer_authorized_products_table"
    observed_at: AwareDatetime
    matches: list[ProductCandidate] = Field(min_length=2, max_length=5)
    more_matches: bool


class ProductSearchArguments(StrictModel):
    question: str = Field(min_length=1, max_length=2000)
    context_handles: list[str] = Field(default_factory=list, max_length=3)
    prefer_descriptions: bool = False


class ProductSearchMatch(StrictModel):
    handle: str = Field(max_length=200)
    title: str = Field(max_length=500)
    vendor: str | None = Field(max_length=200)
    sku: str = Field(max_length=200)
    price: str = Field(max_length=80)
    stock_quantity: int | None = Field(default=None, ge=0)
    currency: str | None = Field(max_length=3)
    source_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    variant_count: int = Field(ge=1)
    specifications: dict[str, str] = Field(default_factory=dict, max_length=6)


class ProductSearchResults(StrictModel):
    authority: Literal["developer_authorized_products_table"] = "developer_authorized_products_table"
    observed_at: AwareDatetime
    matches: list[ProductSearchMatch] = Field(max_length=3)
    more_matches: bool = False
    currency_unverified: bool = False
    database_values_verified: Literal[True] = True
    external_sync_verified: Literal[False] = False


class ProductCategoryArguments(StrictModel):
    pass


class ProductCategoryResults(StrictModel):
    authority: Literal["developer_authorized_products_table"] = "developer_authorized_products_table"
    observed_at: AwareDatetime
    categories: list[str] = Field(max_length=20)
    more_categories: bool = False
    source_file_sha256: list[str] = Field(max_length=20)


class ToolError(StrictModel):
    code: Literal[
        "unknown_tool", "permission_denied", "invalid_arguments", "source_not_found",
        "tool_timeout", "tool_unavailable", "invalid_result",
        "product_not_found", "ambiguous_sku", "too_many_variants",
    ]
    message: str = Field(max_length=200)


class ToolSuccess(StrictModel):
    tool: str = Field(max_length=64)
    ok: Literal[True] = True
    data: SourceStatus | ProductDetails | ProductCandidates | ProductSearchResults | ProductCategoryResults


class ToolFailure(StrictModel):
    tool: str = Field(max_length=64)
    ok: Literal[False] = False
    error: ToolError


ToolResult = ToolSuccess | ToolFailure
