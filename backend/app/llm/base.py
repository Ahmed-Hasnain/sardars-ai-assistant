from dataclasses import dataclass
from typing import Literal, Protocol, TypedDict


class ChatMessage(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class ChatResult:
    text: str
    model: str
    prompt_tokens: int | None
    output_tokens: int | None
    duration_ms: float | None


class ModelError(RuntimeError):
    pass


class ChatModel(Protocol):
    async def chat(self, messages: list[ChatMessage]) -> ChatResult:
        ...
