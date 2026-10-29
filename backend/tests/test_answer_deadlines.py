"""A response deadline covers each authenticated answer route."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from app.api.answer_deadlines import remaining_timeout, within_answer_deadline
from app.auth.dependencies import get_current_user
from app.core.config import Settings
from app.main import app


@pytest.fixture(autouse=True)
def staff_user():
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role="staff")
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.parametrize("endpoint,message,target", [
    ("/api/v1/chat", "Hello", "app.api.chat.answer_model_first"),
    ("/api/v1/chat", "Which brands does Sardars mention?", "app.api.chat.answer_model_first"),
    ("/api/v1/ask", "Which brands?", "app.api.ask.answer_model_first"),
    ("/api/v1/chat", "Recommend black basin mixers under 1000", "app.api.chat.answer_model_first"),
    ("/api/v1/chat", "What is the price of SKU TEST-1?", "app.api.chat.answer_model_first"),
])
def test_slow_answer_returns_safe_timeout_without_partial_citations(monkeypatch, endpoint, message, target):
    monkeypatch.setattr("app.api.answer_deadlines.ANSWER_TIMEOUT_SECONDS", 0.02)

    async def slow(*args, **kwargs):
        await asyncio.sleep(1)
        raise AssertionError("slow answer should have been cancelled")

    with patch(target, new_callable=AsyncMock, side_effect=slow) as service:
        response = TestClient(app).post(endpoint, json={"message": message})
    assert response.status_code == 504
    assert response.json() == {"detail": "Answer timed out"}
    assert "slow answer" not in response.text
    service.assert_awaited_once()


def test_deadline_budget_reaches_threaded_retrieval(monkeypatch):
    monkeypatch.setattr("app.api.answer_deadlines.ANSWER_TIMEOUT_SECONDS", 1.0)

    async def work():
        return await asyncio.to_thread(remaining_timeout, 120.0)

    allowed = asyncio.run(within_answer_deadline(work()))
    assert 0 < allowed <= 1.0
    assert remaining_timeout(120.0) == 120.0  # context is cleared afterward


def test_answer_budget_accepts_five_minutes_but_keeps_a_finite_cap():
    assert Settings(answer_timeout_seconds=300).answer_timeout_seconds == 300
    with pytest.raises(ValidationError):
        Settings(answer_timeout_seconds=301)
