import httpx

from app.core.config import Settings
from app.llm.base import ChatMessage, ChatResult, ModelError


class OllamaChatModel:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def chat(self, messages: list[ChatMessage]) -> ChatResult:
        payload = {
            "model": self.settings.ollama_model,
            "messages": messages,
            "stream": False,
            "think": False,
            "keep_alive": self.settings.ollama_keep_alive,
        }

        try:
            async with httpx.AsyncClient(
                timeout=self.settings.ollama_timeout_seconds
            ) as client:
                response = await client.post(
                    f"{self.settings.ollama_base_url.rstrip('/')}/api/chat",
                    json=payload,
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ModelError("Ollama request failed") from exc

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
