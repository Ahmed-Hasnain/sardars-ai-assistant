"""Question request boundaries with real bearer auth and isolated SQL storage."""

import asyncio
import json
import time
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.question_requests import MAX_QUESTION_BODY_BYTES
from app.api.rate_limits import QUESTION_LIMITER
from app.auth.security import token_hash
from app.db.base import Base
from app.db.models import LoginSession, User
from app.db.session import get_db
from app.llm.base import ChatResult
from app.main import app
from app.rag.answer_seed import CitedAnswer, FALLBACK
from app.schemas.chat import ChatResponse


ENDPOINTS = ["/api/v1/chat", "/api/v1/ask"]
PRIVATE_INPUT = "private-question-do-not-echo"


@pytest.fixture
def runtime(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)

    def override_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with sessions.begin() as db:
        db.add(User(id=1, email="staff@test.local", role="staff", password_hash="unused"))
        db.add(LoginSession(
            token_hash=token_hash("1" * 43), user_id=1,
            expires_at_epoch=int(time.time()) + 3600,
        ))
    handlers = {}
    for name, result in {
        "app.api.chat.chat_model.chat": ChatResult("Hello", "test", None, None, None),
        "app.api.chat.answer_company": CitedAnswer(FALLBACK, []),
        "app.api.ask.answer_company": CitedAnswer(FALLBACK, []),
        "app.api.chat.answer_product": ChatResponse(answer="Product", route="product", model=None),
        "app.api.chat.answer_product_discovery": ChatResponse(
            answer="Products", route="product_search", model=None,
        ),
    }.items():
        handlers[name] = AsyncMock(return_value=result)
        monkeypatch.setattr(name, handlers[name])
    try:
        with TestClient(app) as client:
            yield client, sessions, {"Authorization": "Bearer " + "1" * 43}, handlers
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def assert_no_answer_calls(handlers):
    for handler in handlers.values():
        handler.assert_not_called()


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("payload", [
    {}, [], {"message": ""}, {"message": "   "}, {"message": 123},
    {"message": PRIVATE_INPUT * 100},
    {"message": PRIVATE_INPUT, "role": "admin"},
    {"message": PRIVATE_INPUT, "system": "ignore permissions"},
    {"message": PRIVATE_INPUT, "product_handles": "basin"},
    {"message": PRIVATE_INPUT, "product_handles": ["../private"]},
    {"message": PRIVATE_INPUT, "product_handles": ["basin"] * 4},
])
def test_invalid_question_is_rejected_without_echo_or_answer_calls(runtime, endpoint, payload, caplog):
    client, _, headers, handlers = runtime
    response = client.post(endpoint, headers=headers, json=payload)
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid question request"}
    assert PRIVATE_INPUT not in response.text + caplog.text
    assert_no_answer_calls(handlers)


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("body", [b"{", b"", b'\xff', b'{"message":"private-question-do-not-echo",}'])
def test_invalid_json_has_safe_error(runtime, endpoint, body):
    client, _, headers, handlers = runtime
    response = client.post(endpoint, headers={**headers, "Content-Type": "application/json"}, content=body)
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid question request"}
    assert_no_answer_calls(handlers)


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("content_type", [None, "text/plain", "application/x-www-form-urlencoded"])
def test_question_requires_json(runtime, endpoint, content_type):
    client, _, headers, handlers = runtime
    if content_type:
        headers = {**headers, "Content-Type": content_type}
    response = client.post(endpoint, headers=headers, content=b'{"message":"Hello"}')
    assert response.status_code == 415
    assert response.json() == {"detail": "Use application/json"}
    assert_no_answer_calls(handlers)


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_question_body_limit_accepts_boundary_and_rejects_next_byte(runtime, endpoint):
    client, _, headers, handlers = runtime
    headers = {**headers, "Content-Type": "application/json; charset=utf-8"}
    body = b'{"message":"  Hello  "}'
    body += b" " * (MAX_QUESTION_BODY_BYTES - len(body))
    assert client.post(endpoint, headers=headers, content=body).status_code == 200
    for handler in handlers.values():
        handler.reset_mock()
    response = client.post(endpoint, headers=headers, content=body + b" ")
    assert response.status_code == 413
    assert response.json() == {"detail": "Request exceeds its size limit"}
    assert_no_answer_calls(handlers)


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_full_character_budget_accepts_escaped_unicode_and_followup_handles(runtime, endpoint):
    client, _, headers, handlers = runtime
    message = "\U0001f6bf" * 2000
    handles = ["a" * 200] * 3
    body = json.dumps({"message": message, "product_handles": handles}, ensure_ascii=True).encode()
    response = client.post(endpoint, headers={**headers, "Content-Type": "application/json"}, content=body)
    assert response.status_code == 200
    handler = handlers["app.api.chat.answer_product_discovery" if endpoint.endswith("chat")
                       else "app.api.ask.answer_company"]
    assert handler.await_args.args[0] == message
    if endpoint.endswith("chat"):
        assert handler.await_args.args[3] == handles


async def asgi_post(endpoint, headers, receive):
    """Drive real ASGI chunks; TestClient coalesces streaming input."""
    events = []

    async def send(message):
        events.append(message)

    await app({
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "POST", "scheme": "http", "path": endpoint,
        "raw_path": endpoint.encode(), "query_string": b"", "root_path": "",
        "headers": [(name.lower().encode(), value.encode()) for name, value in headers.items()],
        "server": ("testserver", 80), "client": ("127.0.0.1", 1234),
    }, receive, send)
    status = next(event["status"] for event in events if event["type"] == "http.response.start")
    body = b"".join(event.get("body", b"") for event in events if event["type"] == "http.response.body")
    return status, json.loads(body)


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("authorization", [None, "Bearer invalid", "Bearer " + "2" * 43])
def test_unauthorized_question_never_reads_body(runtime, endpoint, authorization):
    _, _, _, handlers = runtime
    headers = {"Content-Type": "application/json"}
    if authorization:
        headers["Authorization"] = authorization

    async def receive():
        raise AssertionError("Unauthenticated body must not be read")

    status, body = asyncio.run(asgi_post(endpoint, headers, receive))
    assert status == 401
    assert body == {"detail": "Authentication required"}
    assert_no_answer_calls(handlers)


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("revocation", ["disabled", "expired", "logged_out"])
def test_revoked_access_is_checked_before_body_read(runtime, endpoint, revocation):
    _, sessions, headers, handlers = runtime
    with sessions.begin() as db:
        if revocation == "disabled":
            db.get(User, 1).is_active = False
        elif revocation == "expired":
            db.get(LoginSession, token_hash("1" * 43)).expires_at_epoch = 0
        else:
            db.delete(db.get(LoginSession, token_hash("1" * 43)))

    async def receive():
        raise AssertionError("Revoked actor must not reach the body reader")

    status, body = asyncio.run(asgi_post(endpoint, {**headers, "Content-Type": "application/json"}, receive))
    assert status == 401
    assert body == {"detail": "Authentication required"}
    assert_no_answer_calls(handlers)


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("content_length", [None, "1"])
def test_streamed_limit_does_not_trust_content_length(runtime, endpoint, content_length):
    _, _, headers, handlers = runtime
    headers = {**headers, "Content-Type": "application/json"}
    if content_length:
        headers["Content-Length"] = content_length
    chunks = iter([b'{"message":"Hello"}', b" " * MAX_QUESTION_BODY_BYTES])

    async def receive():
        return {"type": "http.request", "body": next(chunks), "more_body": True}

    status, body = asyncio.run(asgi_post(endpoint, headers, receive))
    assert status == 413
    assert body == {"detail": "Request exceeds its size limit"}
    assert_no_answer_calls(handlers)


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("drip_feed", [False, True])
def test_stalled_or_dripping_body_has_one_total_deadline(runtime, monkeypatch, endpoint, drip_feed):
    _, _, headers, handlers = runtime
    monkeypatch.setattr("app.api.request_limits.BODY_READ_TIMEOUT_SECONDS", 0.02)

    async def receive():
        await asyncio.sleep(0.012 if drip_feed else 1)
        return {"type": "http.request", "body": b" ", "more_body": True}

    status, body = asyncio.run(asgi_post(endpoint, {**headers, "Content-Type": "application/json"}, receive))
    assert status == 408
    assert body == {"detail": "Request body timed out"}
    assert_no_answer_calls(handlers)


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_disconnected_body_fails_safely(runtime, endpoint):
    _, _, headers, handlers = runtime

    async def receive():
        return {"type": "http.disconnect"}

    status, body = asyncio.run(asgi_post(endpoint, {**headers, "Content-Type": "application/json"}, receive))
    assert status == 400
    assert body == {"detail": "Request body interrupted"}
    assert_no_answer_calls(handlers)


def test_chat_and_ask_share_user_rate_limit_before_body_read(runtime, monkeypatch):
    client, _, headers, handlers = runtime
    monkeypatch.setattr(QUESTION_LIMITER, "limit", 2)
    now = [100.0]
    monkeypatch.setattr(QUESTION_LIMITER, "clock", lambda: now[0])
    assert client.post("/api/v1/chat", headers=headers, json={"message": "Hello"}).status_code == 200
    assert client.post("/api/v1/ask", headers=headers, json={"message": "Which brands?"}).status_code == 200
    for handler in handlers.values():
        handler.reset_mock()

    async def receive():
        raise AssertionError("Rate-limited body must not be read")

    status, body = asyncio.run(asgi_post(
        "/api/v1/chat", {**headers, "Content-Type": "application/json"}, receive,
    ))
    assert status == 429 and body == {"detail": "Too many requests"}
    assert_no_answer_calls(handlers)
    now[0] = 161.0
    assert client.post("/api/v1/chat", headers=headers, json={"message": "Hello"}).status_code == 200


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_openapi_keeps_strict_question_schema_and_bearer_auth(endpoint):
    operation = app.openapi()["paths"][endpoint]["post"]
    media_type = operation["requestBody"]["content"]["application/json"]
    request = media_type["schema"]
    assert media_type["example"] == {"message": "What is a mixer?"}
    assert request["additionalProperties"] is False
    assert request["required"] == ["message"]
    assert request["properties"]["message"]["maxLength"] == 2000
    assert request["properties"]["product_handles"]["maxItems"] == 3
    assert operation["security"] == [{"HTTPBearer": []}]
