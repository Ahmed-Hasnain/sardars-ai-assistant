"""Owned chat history persists model-first turns without replaying old answers."""

import asyncio
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import time
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.rate_limits import HISTORY_LIMITER
from app.auth.security import token_hash
from app.db.base import Base
from app.db.models import Conversation, ConversationMessage, LoginSession, SourceRegistration, User
from app.db.products import Product
from app.db.session import get_db
from app.llm.base import ModelError
from app.main import app
from app.schemas.ask import SourceCitation
from app.schemas.chat import ChatResponse
from app.services.conversations import (
    ConversationConflict, TurnContext, inferred_product_handles, load_owned, purge_expired, save_turn,
)


@pytest.fixture
def runtime():
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    now = int(time.time())
    with sessions.begin() as db:
        for identity, role in ((1, "staff"), (2, "staff"), (3, "admin")):
            db.add(User(id=identity, email=f"person{identity}@example.test", role=role, password_hash="unused"))
            db.add(LoginSession(token_hash=token_hash(str(identity) * 43), user_id=identity,
                                expires_at_epoch=now + 3600))

    def override_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            yield client, sessions
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def headers(identity=1):
    return {"Authorization": "Bearer " + str(identity) * 43}


def _answer(text="Hello", route="general", **kwargs):
    return ChatResponse(answer=text, route=route, model="test-model", **kwargs)


def test_unknown_conversation_is_not_created(runtime):
    client, _ = runtime
    with patch("app.api.chat.answer_model_first", new_callable=AsyncMock) as service:
        response = client.post("/api/v1/chat", headers=headers(), json={
            "message": "Hello", "conversation_id": "166757ad-ed0e-3528-d196-0641a5810855",
        })
    assert response.status_code == 404
    service.assert_not_called()
    assert client.get("/api/v1/conversations", headers=headers()).json() == []


def test_followup_persists_and_passes_only_prior_user_question(runtime):
    client, sessions = runtime
    with patch("app.api.chat.answer_model_first", new_callable=AsyncMock,
               side_effect=[_answer("A mixer combines water."), _answer("It combines hot and cold water.")]) as service:
        first = client.post("/api/v1/chat", headers=headers(), json={"message": "What is a mixer?"})
        identity = first.json()["conversation_id"]
        second = client.post("/api/v1/chat", headers=headers(), json={
            "message": "How does it work?", "conversation_id": identity,
        })
    assert first.status_code == second.status_code == 200
    assert second.json()["conversation_id"] == identity
    assert service.await_args_list[1].kwargs["previous_question"] == "What is a mixer?"
    assert "A mixer combines water" not in str(service.await_args_list[1])
    page = client.get(f"/api/v1/conversations/{identity}", headers=headers()).json()
    assert [item["role"] for item in page["messages"]] == ["user", "assistant", "user", "assistant"]
    assert page["messages"][1]["model"] == "test-model"
    with sessions() as db:
        assert len(db.scalars(select(ConversationMessage)).all()) == 4


def test_company_followup_expands_search_without_replaying_old_answer(runtime):
    client, _ = runtime
    with patch("app.api.chat.answer_model_first", new_callable=AsyncMock,
               return_value=_answer("I cannot verify that yet.", "company")) as service:
        identity = client.post("/api/v1/chat", headers=headers(), json={
            "message": "Which brands does Sardars mention?",
        }).json()["conversation_id"]
        response = client.post("/api/v1/chat", headers=headers(), json={
            "conversation_id": identity, "message": "What about their warranty?",
        })
    assert response.status_code == 200
    assert "Which brands does Sardars mention?" in service.await_args_list[1].kwargs["search_query"]
    assert service.await_args_list[1].kwargs["previous_question"] == "Which brands does Sardars mention?"


def test_streamed_turn_is_saved_before_delivery(runtime):
    client, sessions = runtime
    with patch("app.api.chat.answer_model_first", new_callable=AsyncMock,
               return_value=_answer("A mixer combines water.")):
        response = client.post("/api/v1/chat/stream", headers=headers(), json={"message": "What is a mixer?"})
    assert response.status_code == 200 and "event: complete" in response.text
    identity = client.get("/api/v1/conversations", headers=headers()).json()[0]["id"]
    page = client.get(f"/api/v1/conversations/{identity}", headers=headers()).json()
    assert page["messages"][1]["content"] == "A mixer combines water."
    assert client.get(f"/api/v1/conversations/{identity}", headers=headers(2)).status_code == 404
    with sessions() as db:
        assert len(db.scalars(select(ConversationMessage)).all()) == 2


def test_product_followup_reuses_handles_for_fresh_service_call(runtime):
    client, _ = runtime
    with patch("app.api.chat.answer_model_first", new_callable=AsyncMock, side_effect=[
        _answer("two products", "product_search", product_handles=["basin-one", "basin-two"]),
        _answer("fresh comparison", "product_search", product_handles=["basin-one", "basin-two"]),
    ]) as service:
        identity = client.post("/api/v1/chat", headers=headers(), json={
            "message": "Recommend basin mixers",
        }).json()["conversation_id"]
        result = client.post("/api/v1/chat", headers=headers(), json={
            "message": "Which of these is cheaper?", "conversation_id": identity,
        })
    assert result.status_code == 200 and result.json()["answer"] == "fresh comparison"
    assert service.await_args_list[1].kwargs["product_handles"] == ["basin-one", "basin-two"]


def test_cross_user_and_role_downgrade_hide_history(runtime):
    client, sessions = runtime
    with patch("app.api.chat.answer_model_first", new_callable=AsyncMock, return_value=_answer()) as service:
        identity = client.post("/api/v1/chat", headers=headers(3), json={"message": "Hello"}).json()["conversation_id"]
        assert client.get(f"/api/v1/conversations/{identity}", headers=headers()).status_code == 404
        assert client.post("/api/v1/chat", headers=headers(), json={
            "conversation_id": identity, "message": "Hello",
        }).status_code == 404
        with sessions.begin() as db:
            db.get(User, 3).role = "staff"
        assert client.get(f"/api/v1/conversations/{identity}", headers=headers(3)).status_code == 404
        assert client.post("/api/v1/chat", headers=headers(3), json={
            "conversation_id": identity, "message": "Hello",
        }).status_code == 404
    service.assert_awaited_once()


def test_revoked_source_redacts_historical_answer(runtime):
    client, sessions = runtime
    url = "https://sardarandco.com/pages/about-us"
    source_id = sha256(url.encode()).hexdigest()
    with sessions.begin() as db:
        db.add(SourceRegistration(source_id=source_id, url=url, source_type="pages",
                                  content_sha256="a" * 64, visibility="staff", is_active=True,
                                  authorization_basis="test", title="About Us"))
    citation = SourceCitation(number=1, source_id=source_id, title="About Us", url=url, fetched_at=None)
    with patch("app.api.chat.answer_model_first", new_callable=AsyncMock,
               return_value=_answer("Private source answer [1]", "company", sources=[citation])):
        identity = client.post("/api/v1/chat", headers=headers(), json={
            "message": "Which brands does Sardars mention?",
        }).json()["conversation_id"]
    assert "Private source answer" in client.get(f"/api/v1/conversations/{identity}", headers=headers()).text
    with sessions.begin() as db:
        db.get(SourceRegistration, source_id).visibility = "admin"
    page = client.get(f"/api/v1/conversations/{identity}", headers=headers()).json()
    assert page["messages"][1]["sources"] == []
    assert "Private source answer" not in str(page)


def test_hidden_product_redacts_historical_answer(runtime):
    client, sessions = runtime
    with sessions.begin() as db:
        db.add(Product(source_file_name="test.csv", source_file_sha256="a" * 64,
                       source_row_number=1, handle="basin-one", status="active", visibility="staff"))
    with patch("app.api.chat.answer_model_first", new_callable=AsyncMock,
               return_value=_answer("Historical product price 100", "product_search", product_handles=["basin-one"])):
        identity = client.post("/api/v1/chat", headers=headers(), json={
            "message": "Recommend basin mixers",
        }).json()["conversation_id"]
    assert "Historical product price" in client.get(f"/api/v1/conversations/{identity}", headers=headers()).text
    with sessions.begin() as db:
        db.scalar(select(Product)).visibility = "admin"
    page = client.get(f"/api/v1/conversations/{identity}", headers=headers()).json()
    assert page["messages"][1]["content"] != "Historical product price 100"
    assert page["messages"][1]["product_handles"] == []


def test_corrupt_saved_handles_are_not_reused(runtime):
    client, sessions = runtime
    with patch("app.api.chat.answer_model_first", new_callable=AsyncMock,
               return_value=_answer("products", "product_search", product_handles=["basin-one"])):
        identity = client.post("/api/v1/chat", headers=headers(), json={
            "message": "Recommend basin mixers",
        }).json()["conversation_id"]
    with sessions.begin() as db:
        db.scalar(select(ConversationMessage).where(ConversationMessage.role == "assistant")).product_handles = ["../private"]
    with sessions() as db:
        context = load_owned(db, db.get(User, 1), identity)
        assert inferred_product_handles("Which of these is cheaper?", context) == []


def test_this_product_carries_only_the_previous_product_handle():
    context = TurnContext(
        conversation=None, version=1,
        recent=(
            ConversationMessage(role="user", content="Show SKU TEST-1701"),
            ConversationMessage(role="assistant", content="Catalog result", route="product",
                                product_handles=["1689"]),
        ),
    )
    assert inferred_product_handles("What category is this product?", context) == ["1689"]
    assert inferred_product_handles("What is the return policy of this product?", context) == []


def test_expired_conversation_is_inaccessible_and_purged(runtime):
    client, sessions = runtime
    with patch("app.api.chat.answer_model_first", new_callable=AsyncMock, return_value=_answer()):
        identity = client.post("/api/v1/chat", headers=headers(), json={"message": "Hello"}).json()["conversation_id"]
    with sessions.begin() as db:
        db.get(Conversation, identity).expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert client.get(f"/api/v1/conversations/{identity}", headers=headers()).status_code == 404
    with sessions() as db:
        assert purge_expired(db) == 1
        assert db.get(Conversation, identity) is None
        assert db.scalars(select(ConversationMessage)).all() == []


def test_failed_and_timed_out_answers_are_not_saved(runtime, monkeypatch):
    client, sessions = runtime
    with patch("app.api.chat.answer_model_first", new_callable=AsyncMock, side_effect=ModelError("secret")):
        failed = client.post("/api/v1/chat", headers=headers(), json={"message": "Hello"})
    assert failed.status_code == 503 and "secret" not in failed.text
    monkeypatch.setattr("app.api.answer_deadlines.ANSWER_TIMEOUT_SECONDS", 0.01)

    async def slow(*args, **kwargs):
        await asyncio.sleep(0.1)
        return _answer("late")

    with patch("app.api.chat.answer_model_first", new_callable=AsyncMock, side_effect=slow):
        timed_out = client.post("/api/v1/chat", headers=headers(), json={"message": "Hello"})
    assert timed_out.status_code == 504
    with sessions() as db:
        assert db.scalars(select(Conversation)).all() == []


def test_history_requires_authentication_and_rate_limits(runtime, monkeypatch):
    client, _ = runtime
    assert client.get("/api/v1/conversations").status_code == 401
    monkeypatch.setattr(HISTORY_LIMITER, "limit", 2)
    assert client.get("/api/v1/conversations", headers=headers()).status_code == 200
    assert client.get("/api/v1/conversations", headers=headers()).status_code == 200
    assert client.get("/api/v1/conversations", headers=headers()).status_code == 429


def test_invalid_conversation_id_is_rejected_before_answer(runtime):
    client, _ = runtime
    with patch("app.api.chat.answer_model_first", new_callable=AsyncMock) as service:
        response = client.post("/api/v1/chat", headers=headers(), json={
            "message": "Hello", "conversation_id": "../another-user",
        })
    assert response.status_code == 422
    service.assert_not_called()


def test_pagination_delete_and_stale_write(runtime):
    client, sessions = runtime
    with patch("app.api.chat.answer_model_first", new_callable=AsyncMock, return_value=_answer()):
        identity = client.post("/api/v1/chat", headers=headers(), json={"message": "Hello"}).json()["conversation_id"]
        for _ in range(2):
            assert client.post("/api/v1/chat", headers=headers(), json={
                "conversation_id": identity, "message": "Hello",
            }).status_code == 200
    latest = client.get(f"/api/v1/conversations/{identity}?limit=2", headers=headers()).json()
    assert len(latest["messages"]) == 2 and latest["next_before_message_id"] is not None
    earlier = client.get(f"/api/v1/conversations/{identity}", headers=headers(), params={
        "limit": 2, "before_message_id": latest["next_before_message_id"],
    }).json()
    assert len(earlier["messages"]) == 2
    with sessions() as first_db, sessions() as second_db:
        first = load_owned(first_db, first_db.get(User, 1), identity)
        stale = load_owned(second_db, second_db.get(User, 1), identity)
        save_turn(first_db, first_db.get(User, 1), "next", [], _answer("next"), first)
        with pytest.raises(ConversationConflict):
            save_turn(second_db, second_db.get(User, 1), "stale", [], _answer("stale"), stale)
        second_db.rollback()
    assert client.delete(f"/api/v1/conversations/{identity}", headers=headers()).status_code == 204
    with sessions() as db:
        assert db.scalars(select(ConversationMessage)).all() == []
