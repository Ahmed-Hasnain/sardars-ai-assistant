from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
import pytest

from app.auth.dependencies import get_current_user
from app.llm.base import ChatResult, ModelError
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def authenticated_user():
    app.dependency_overrides[get_current_user] = lambda: object()
    yield
    app.dependency_overrides.pop(get_current_user, None)


def test_chat_returns_unverified_answer() -> None:
    result = ChatResult("Hello!", "test-model", 5, 2, 10.0)
    with patch("app.api.chat.chat_model.chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.return_value = result
        response = client.post("/api/v1/chat", json={"message": "  Hello  "})

    assert response.status_code == 200
    assert response.json()["answer"] == "Hello!"
    assert response.json()["company_data_verified"] is False
    assert mock_chat.await_args.args[0][-1]["content"] == "Hello"


def test_chat_rejects_blank_message() -> None:
    response = client.post("/api/v1/chat", json={"message": "   "})
    assert response.status_code == 422


def test_chat_reports_model_failure() -> None:
    with patch("app.api.chat.chat_model.chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.side_effect = ModelError("Connection failed")
        response = client.post("/api/v1/chat", json={"message": "Hello"})

    assert response.status_code == 503
    assert response.json() == {"detail": "Local model unavailable"}
