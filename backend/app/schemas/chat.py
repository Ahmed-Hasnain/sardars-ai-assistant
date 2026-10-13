from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.ask import SourceCitation


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)

    @field_validator("message")
    @classmethod
    def strip_message(cls, value: str) -> str:
        message = value.strip()
        if not message:
            raise ValueError("Message cannot be empty")
        return message


class ChatResponse(BaseModel):
    answer: str
    route: Literal["general", "company"]
    sources: list[SourceCitation] = Field(default_factory=list)
    model: str | None
    company_data_verified: Literal[False] = False
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    duration_ms: float | None = None
