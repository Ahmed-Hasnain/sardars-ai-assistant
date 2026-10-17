"""The local adapter bounds generation and rejects oversized model replies."""

import asyncio

import httpx
import pytest

from app.core.config import Settings
from app.llm.base import ModelError
from app.llm.ollama import OllamaChatModel


def test_chat_caps_predicted_tokens_and_accepts_small_reply(monkeypatch):
    seen = []
    real_client = httpx.AsyncClient

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"message": {"content": "A mixer blends water."}, "model": "test"})

    monkeypatch.setattr("app.llm.ollama.httpx.AsyncClient", lambda **kw: real_client(
        transport=httpx.MockTransport(handler), timeout=kw["timeout"],
    ))
    result = asyncio.run(OllamaChatModel(Settings()).chat([
        {"role": "user", "content": "What is a mixer?"},
    ]))
    assert result.text == "A mixer blends water."
    assert seen[0].read().decode().count('"num_predict":256') == 1


def test_oversized_model_reply_does_not_reach_answer(monkeypatch):
    real_client = httpx.AsyncClient

    def handler(request):
        return httpx.Response(200, json={"message": {"content": "private " * 10000}, "model": "test"})

    monkeypatch.setattr("app.llm.ollama.httpx.AsyncClient", lambda **kw: real_client(
        transport=httpx.MockTransport(handler), timeout=kw["timeout"],
    ))
    with pytest.raises(ModelError, match="response too large"):
        asyncio.run(OllamaChatModel(Settings()).chat([
            {"role": "user", "content": "What is a mixer?"},
        ]))
