"""The live HTTP chat routes forward authorized questions to the model-first service."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
import pytest

from app.auth.dependencies import get_current_user
from app.llm.base import ModelError
from app.main import app
from app.schemas.ask import SourceCitation
from app.schemas.chat import ChatResponse


@pytest.fixture(autouse=True)
def staff_user():
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role="staff")
    yield
    app.dependency_overrides.pop(get_current_user, None)


def _answer(text="Hello from the model.", route="general", sources=None):
    return ChatResponse(answer=text, route=route, model="test-model", sources=sources or [])


@pytest.mark.parametrize("question", [
    "hello how are you", "what is sardars?", "can you give me some products of bongio",
    "what is Bongio", "what do people say about Sardars", "what are your product categories",
    "what is the address of the store", "who are Sardars' competitors",
])
def test_chat_passes_each_normal_question_to_model_service(question):
    with patch("app.api.chat.answer_model_first", new_callable=AsyncMock, return_value=_answer()) as service:
        response = TestClient(app).post("/api/v1/chat", json={"message": question})
    assert response.status_code == 200
    assert response.json()["answer"] == "Hello from the model."
    assert service.await_args.args[0] == question


def test_ask_passes_question_to_same_model_service_and_returns_citations():
    source = SourceCitation(number=1, source_id="a" * 64, title="About us",
                            url="https://sardarandco.com/pages/about-us", fetched_at=None)
    with patch("app.api.ask.answer_model_first", new_callable=AsyncMock,
               return_value=_answer("Sardars sells bathroom fittings. [1]", "company", [source])) as service:
        response = TestClient(app).post("/api/v1/ask", json={"message": "what is sardars?"})
    assert response.status_code == 200
    assert response.json()["answer"].endswith("[1]")
    assert response.json()["sources"][0]["source_id"] == "a" * 64
    service.assert_awaited_once()


def test_stream_emits_complete_answer_after_service_finishes():
    text = "A cited answer. " * 15
    with patch("app.api.chat.answer_model_first", new_callable=AsyncMock, return_value=_answer(text)):
        response = TestClient(app).post("/api/v1/chat/stream", json={"message": "Tell me more"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = [part for part in response.text.split("\n\n") if part]
    assert events[0].startswith("event: start\n")
    assert sum(part.startswith("event: chunk\n") for part in events) > 1
    assert json.loads(events[-1].split("data: ", 1)[1])["answer"] == text


def test_model_error_is_safe_and_no_partial_stream_is_sent():
    with patch("app.api.chat.answer_model_first", new_callable=AsyncMock,
               side_effect=ModelError("private model detail")):
        response = TestClient(app).post("/api/v1/chat/stream", json={"message": "hello"})
    assert response.status_code == 503
    assert response.json() == {"detail": "Answer service unavailable"}
    assert "private model detail" not in response.text


def test_blank_message_is_rejected_before_service():
    with patch("app.api.chat.answer_model_first", new_callable=AsyncMock) as service:
        response = TestClient(app).post("/api/v1/chat", json={"message": "   "})
    assert response.status_code == 422
    service.assert_not_called()


def test_ask_rejects_conversation_followup():
    with patch("app.api.ask.answer_model_first", new_callable=AsyncMock) as service:
        response = TestClient(app).post("/api/v1/ask", json={
            "message": "hello", "conversation_id": "00000000-0000-0000-0000-000000000001",
        })
    assert response.status_code == 422
    service.assert_not_called()


def test_anonymous_chat_never_calls_model():
    app.dependency_overrides.pop(get_current_user, None)
    with patch("app.api.chat.answer_model_first", new_callable=AsyncMock) as service:
        response = TestClient(app).post("/api/v1/chat", json={"message": "hello"})
    assert response.status_code == 401
    service.assert_not_called()
