"""Strict inputs and bounded structured results for the first read tool."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


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


class ToolError(StrictModel):
    code: Literal[
        "unknown_tool", "permission_denied", "invalid_arguments", "source_not_found",
        "tool_timeout", "tool_unavailable", "invalid_result",
    ]
    message: str = Field(max_length=200)


class ToolSuccess(StrictModel):
    tool: str = Field(max_length=64)
    ok: Literal[True] = True
    data: SourceStatus


class ToolFailure(StrictModel):
    tool: str = Field(max_length=64)
    ok: Literal[False] = False
    error: ToolError


ToolResult = ToolSuccess | ToolFailure
