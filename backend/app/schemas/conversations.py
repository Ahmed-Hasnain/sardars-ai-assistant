"""Bounded conversation history responses for the owning staff account."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.ask import SourceCitation


class ConversationSummary(BaseModel):
    id: str
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    preview: str | None = None


class MessageView(BaseModel):
    id: int
    role: str
    content: str
    route: str | None
    model: str | None
    prompt_tokens: int | None
    output_tokens: int | None
    duration_ms: float | None
    product_handles: list[str]
    sources: list[SourceCitation] = Field(default_factory=list)
    created_at: datetime


class ConversationPage(BaseModel):
    conversation: ConversationSummary
    messages: list[MessageView]
    next_before_message_id: int | None
    historical_notice: str = "Earlier answers are historical. Recheck prices, stock, and policies. Citations link currently authorized sources whose content may have changed."
