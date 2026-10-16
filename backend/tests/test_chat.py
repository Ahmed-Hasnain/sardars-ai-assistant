from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from app.auth.dependencies import get_current_user
from app.llm.base import ChatResult, ModelError
from app.rag.answer_seed import CitedAnswer, CitedSource, FALLBACK
from app.main import app
from app.schemas.chat import ChatResponse

client = TestClient(app)


@pytest.fixture(autouse=True)
def authenticated_user():
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role="staff")
    yield
    app.dependency_overrides.pop(get_current_user, None)


def test_chat_returns_unverified_answer() -> None:
    result = ChatResult("Hello!", "test-model", 5, 2, 10.0)
    with patch("app.api.chat.chat_model.chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.return_value = result
        response = client.post("/api/v1/chat", json={"message": "  Hello  "})

    assert response.status_code == 200
    assert response.json()["answer"] == "Hello!"
    assert response.json()["route"] == "general"
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


def test_chat_routes_sardars_question_to_grounded_answer() -> None:
    cited = CitedAnswer(
        "Sardars mentions Grohe. [1]",
        [CitedSource(1, "a" * 64, "About Us", "https://sardarandco.com/pages/about-us", None)],
        "test-model",
    )
    with patch("app.api.chat.answer_company", new_callable=AsyncMock) as answer:
        answer.return_value = cited
        response = client.post(
            "/api/v1/chat", json={"message": "Which brands does Sardars mention?"}
        )

    assert response.status_code == 200
    assert response.json()["route"] == "company"
    assert response.json()["sources"][0]["number"] == 1
    assert response.json()["sources"][0]["source_id"] == "a" * 64
    assert answer.await_args.args[1] == "staff"


def test_chat_company_abstention_has_no_citation() -> None:
    with patch("app.api.chat.answer_company", new_callable=AsyncMock) as answer:
        answer.return_value = CitedAnswer(FALLBACK, [])
        response = client.post(
            "/api/v1/chat", json={"message": "What is your return policy?"}
        )

    assert response.status_code == 200
    assert response.json()["route"] == "company"
    assert response.json()["answer"] == FALLBACK
    assert response.json()["sources"] == []


def test_chat_routes_exact_product_price_question_to_tool_flow() -> None:
    with patch("app.api.chat.answer_product", new_callable=AsyncMock) as product:
        product.return_value = ChatResponse(answer="test price 150", route="product", model="test-model")
        response = client.post("/api/v1/chat", json={"message": "What is the price of SKU TEST-1?"})
    assert response.status_code == 200
    assert response.json()["route"] == "product"
    product.assert_awaited_once()
