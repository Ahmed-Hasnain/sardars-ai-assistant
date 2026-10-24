from typing import Any

import httpx

from app.api.answer_deadlines import remaining_timeout
from app.core.config import Settings
from app.llm.base import ChatMessage, ChatResult, ModelError, ModelToolCall, ToolChatResult


class OllamaChatModel:
    def __init__(self, settings: Settings, *, output_limit: int = 256, tool_output_limit: int = 256):
        self.settings = settings
        self.output_limit = output_limit
        self.tool_output_limit = tool_output_limit

    async def chat(self, messages: list[ChatMessage]) -> ChatResult:
        payload = {
            "model": self.settings.ollama_model,
            "messages": messages,
            "stream": False,
            "think": False,
            "keep_alive": self.settings.ollama_chat_keep_alive,
            "options": {"num_predict": self.output_limit},
        }

        try:
            async with httpx.AsyncClient(
                timeout=remaining_timeout(self.settings.ollama_timeout_seconds)
            ) as client:
                response = await client.post(
                    f"{self.settings.ollama_base_url.rstrip('/')}/api/chat",
                    json=payload,
                    timeout=remaining_timeout(self.settings.ollama_timeout_seconds),
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ModelError("Ollama request failed") from exc

        if len(response.content) > 64 * 1024:
            raise ModelError("Ollama response too large")
        try:
            body = response.json()
            answer = body["message"]["content"]
            model = body["model"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ModelError("Ollama returned an invalid response") from exc

        if not isinstance(answer, str) or not answer.strip():
            raise ModelError("Ollama returned an empty answer")
        if not isinstance(model, str) or not model:
            raise ModelError("Ollama returned an invalid model name")

        prompt_tokens = body.get("prompt_eval_count")
        output_tokens = body.get("eval_count")
        duration_ns = body.get("total_duration")

        return ChatResult(
            text=answer.strip(),
            model=model,
            prompt_tokens=prompt_tokens if isinstance(prompt_tokens, int) else None,
            output_tokens=output_tokens if isinstance(output_tokens, int) else None,
            duration_ms=duration_ns / 1_000_000 if isinstance(duration_ns, int) else None,
        )

    async def chat_with_tools(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ToolChatResult:
        payload = {
            "model": self.settings.ollama_model,
            "messages": messages,
            "tools": tools,
            "stream": False,
            "think": False,
            "keep_alive": self.settings.ollama_chat_keep_alive,
            "options": {"num_predict": self.tool_output_limit},
        }
        try:
            async with httpx.AsyncClient(timeout=min(self.settings.ollama_timeout_seconds, 60.0)) as client:
                response = await client.post(
                    f"{self.settings.ollama_base_url.rstrip('/')}/api/chat", json=payload,
                )
                response.raise_for_status()
            if len(response.content) > 64 * 1024:
                raise ModelError("Ollama tool response too large")
            body = response.json()
            message = body["message"]
            model = body["model"]
            content = message.get("content", "")
            raw_calls = message.get("tool_calls") or []
            if not isinstance(model, str) or not model or not isinstance(content, str):
                raise ValueError("Invalid model response")
            if not isinstance(raw_calls, list) or len(raw_calls) > 5:
                raise ValueError("Invalid tool calls")
            calls = []
            for item in raw_calls:
                function = item["function"]
                name, arguments = function["name"], function["arguments"]
                if not isinstance(name, str) or not isinstance(arguments, dict):
                    raise ValueError("Invalid tool call")
                calls.append(ModelToolCall(name, arguments))
            duration_ns = body.get("total_duration")
            return ToolChatResult(
                text=content[:2000], model=model, tool_calls=tuple(calls),
                prompt_tokens=body.get("prompt_eval_count") if type(body.get("prompt_eval_count")) is int else None,
                output_tokens=body.get("eval_count") if type(body.get("eval_count")) is int else None,
                duration_ms=duration_ns / 1_000_000 if type(duration_ns) is int else None,
            )
        except httpx.HTTPError as exc:
            raise ModelError("Ollama tool request failed") from exc
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            raise ModelError("Ollama returned an invalid tool response") from exc
