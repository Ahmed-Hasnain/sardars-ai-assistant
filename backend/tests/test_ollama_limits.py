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
    assert seen[0].read().decode().count('"keep_alive":300') == 1


def test_checked_answer_can_request_a_smaller_generation_bound(monkeypatch):
    seen = []
    real_client = httpx.AsyncClient

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"message": {"content": "READY"}, "model": "test"})

    monkeypatch.setattr("app.llm.ollama.httpx.AsyncClient", lambda **kw: real_client(
        transport=httpx.MockTransport(handler), timeout=kw["timeout"],
    ))
    model = OllamaChatModel(Settings(), output_limit=160)
    result = asyncio.run(model.chat([{"role": "user", "content": "Question"}], output_limit=12))
    assert result.text == "READY"
    assert '"num_predict":12' in seen[0].read().decode()
    with pytest.raises(ValueError, match="configured bound"):
        asyncio.run(model.chat([{"role": "user", "content": "Question"}], output_limit=161))
    assert len(seen) == 1


def test_tool_chat_uses_chat_residency_not_ingestion_setting(monkeypatch):
    requests = []
    real_client = httpx.AsyncClient

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"message": {"content": "", "tool_calls": []}, "model": "test"})

    monkeypatch.setattr("app.llm.ollama.httpx.AsyncClient", lambda **kw: real_client(
        transport=httpx.MockTransport(handler), timeout=kw["timeout"],
    ))
    settings = Settings().model_copy(update={"ollama_keep_alive": 0, "ollama_chat_keep_alive": 300})
    asyncio.run(OllamaChatModel(settings).chat_with_tools([{"role": "user", "content": "Hello"}], []))
    assert requests[0].read().decode().count('"keep_alive":300') == 1


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
