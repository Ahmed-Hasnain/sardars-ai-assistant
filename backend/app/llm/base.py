from dataclasses import dataclass
from typing import Any, Literal, Protocol, TypedDict


class ChatMessage(TypedDict):
    role: Literal["system", "user", "assistant", "tool"]
    content: str


@dataclass(frozen=True)
class ChatResult:
    text: str
    model: str
    prompt_tokens: int | None
    output_tokens: int | None
    duration_ms: float | None


@dataclass(frozen=True)
class ModelToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolChatResult:
    text: str
    model: str
    tool_calls: tuple[ModelToolCall, ...]
    prompt_tokens: int | None
    output_tokens: int | None
    duration_ms: float | None


class ModelError(RuntimeError):
    pass


class ChatModel(Protocol):
    async def chat(self, messages: list[ChatMessage], *, output_limit: int | None = None) -> ChatResult:
        ...

    async def chat_with_tools(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ToolChatResult:
        ...
