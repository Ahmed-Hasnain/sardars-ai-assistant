"""Real authentication/SQL reads, isolated from company data and local models."""

from datetime import datetime, timezone
from hashlib import sha256
import logging
import time
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.security import token_hash
from app.api.rate_limits import TOOL_LIMITER
from app.db.base import Base
from app.db.models import LoginSession, SourceRegistration, User
from app.db.session import get_db
from app.main import app
from app.services.source_status import get_source_status
from app.tools import registry
from app.tools.schemas import ToolInvocation


URL = "https://sardarandco.com/pages/test-source"
SOURCE_ID = sha256(URL.encode()).hexdigest()
FETCHED = datetime(2026, 10, 12, 10, tzinfo=timezone.utc)
INDEXED = datetime(2026, 10, 15, 1, tzinfo=timezone.utc)
ENDPOINT = "/api/v1/tools/execute"
CALL = {"name": "get_source_status", "arguments": {"source_id": SOURCE_ID}}


@pytest.fixture
def runtime():
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
        for number, role in enumerate(("staff", "admin"), 1):
            db.add(User(id=number, email=f"{role}@test.local", role=role, password_hash="unused"))
            db.add(LoginSession(
                token_hash=token_hash(str(number) * 43), user_id=number,
                expires_at_epoch=int(time.time()) + 3600,
            ))
        db.add(SourceRegistration(
            source_id=SOURCE_ID, url=URL, title="Test source", source_type="pages",
            content_sha256="a" * 64, visibility="public", is_active=True,
            index_status="ready", authorization_basis="test_source_authorization",
            fetched_at=FETCHED, last_indexed_at=INDEXED, last_synced_at=INDEXED,
            storage_key="private-storage-key", registered_by_user_id=2,
        ))
    try:
        with TestClient(app) as client:
            headers = {
                role: {"Authorization": "Bearer " + str(number) * 43}
                for number, role in enumerate(("staff", "admin"), 1)
            }
            yield client, sessions, headers, engine
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_authentication_precedes_body_parsing_and_execution(runtime, monkeypatch):
    client, _, _, _ = runtime
    execute = Mock(side_effect=AssertionError("must not run"))
    monkeypatch.setattr("app.api.tools.execute_tool", execute)
    assert client.post(ENDPOINT, content="not json").status_code == 401
    assert client.post(ENDPOINT, content=b"x" * 9000).status_code == 401
    execute.assert_not_called()


def test_tool_calls_are_rate_limited_before_parsing(runtime, monkeypatch):
    client, _, headers, _ = runtime
    monkeypatch.setattr(TOOL_LIMITER, "limit", 1)
    assert client.post(ENDPOINT, headers=headers["staff"], json=CALL).status_code == 200
    blocked = client.post(ENDPOINT, headers={**headers["staff"], "Content-Type": "application/json"},
                          content=b"broken")
    assert blocked.status_code == 429
    assert blocked.json() == {"detail": "Too many requests"}
    assert int(blocked.headers["Retry-After"]) >= 1


def test_exact_metadata_read_returns_provenance_without_private_fields_or_writes(runtime):
    client, sessions, headers, engine = runtime
    statements = []

    def record(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        response = client.post(ENDPOINT, headers=headers["staff"], json=CALL)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["source_id"] == SOURCE_ID and data["url"] == URL
    assert data["authority"] == "application_source_registry"
    assert data["retrieval_ready"] is True
    assert data["fetched_at"] == "2026-10-12T10:00:00Z"
    assert data["last_indexed_at"] == "2026-10-15T01:00:00Z"
    assert data["last_synced_at"] == data["last_indexed_at"]
    assert datetime.fromisoformat(data["observed_at"]).tzinfo is not None
    assert data["company_facts_verified"] is False
    assert "private-storage-key" not in response.text
    assert "content_sha256" not in data and "registered_by_user_id" not in data
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)
    with sessions() as db:
        assert db.scalar(select(SourceRegistration)).last_synced_at == INDEXED.replace(tzinfo=None)


@pytest.mark.parametrize("visibility", ["public", "staff", "admin"])
def test_roles_follow_existing_source_visibility(runtime, visibility):
    client, sessions, headers, _ = runtime
    with sessions.begin() as db:
        db.get(SourceRegistration, SOURCE_ID).visibility = visibility
    staff = client.post(ENDPOINT, headers=headers["staff"], json=CALL).json()
    admin = client.post(ENDPOINT, headers=headers["admin"], json=CALL).json()
    assert admin["ok"] is True
    assert staff["ok"] is (visibility != "admin")
    if visibility == "admin":
        missing = client.post(ENDPOINT, headers=headers["staff"], json={
            **CALL, "arguments": {"source_id": "0" * 64},
        }).json()
        assert staff == missing
        assert SOURCE_ID not in str(staff) and URL not in str(staff)


@pytest.mark.parametrize("is_active,index_status", [
    (False, "ready"), (True, "indexing"), (True, "failed"), (False, "removed"),
])
def test_nonready_sources_report_status_without_claiming_retrieval_ready(runtime, is_active, index_status):
    client, sessions, headers, _ = runtime
    with sessions.begin() as db:
        source = db.get(SourceRegistration, SOURCE_ID)
        source.is_active, source.index_status = is_active, index_status
    data = client.post(ENDPOINT, headers=headers["staff"], json=CALL).json()["data"]
    assert data["is_active"] is is_active
    assert data["index_status"] == index_status and data["retrieval_ready"] is False


def test_missing_dates_are_unknown_not_replaced_by_observation_time(runtime):
    client, sessions, headers, _ = runtime
    with sessions.begin() as db:
        source = db.get(SourceRegistration, SOURCE_ID)
        source.fetched_at = source.last_indexed_at = source.last_synced_at = None
    data = client.post(ENDPOINT, headers=headers["staff"], json=CALL).json()["data"]
    assert data["fetched_at"] is data["last_indexed_at"] is data["last_synced_at"] is None


@pytest.mark.parametrize("arguments", [
    {}, {"source_id": 123}, {"source_id": "x" * 64}, {"source_id": "A" * 64},
    {"source_id": SOURCE_ID, "role": "admin"}, {"source_id": SOURCE_ID, "sql": "DROP TABLE users"},
])
def test_invalid_tool_arguments_never_reach_the_lookup(runtime, monkeypatch, arguments):
    client, _, headers, _ = runtime
    lookup = Mock(side_effect=AssertionError("must not run"))
    monkeypatch.setattr(registry, "get_source_status", lookup)
    body = client.post(ENDPOINT, headers=headers["staff"], json={**CALL, "arguments": arguments}).json()
    assert body["ok"] is False and body["error"]["code"] == "invalid_arguments"
    lookup.assert_not_called()


@pytest.mark.parametrize("body", [
    {**CALL, "role": "admin"}, {**CALL, "arguments": []}, {**CALL, "name": 123},
    {**CALL, "name": "get_source_status; DROP TABLE users"}, [CALL, CALL],
])
def test_invalid_envelopes_are_rejected_without_echoing_input(runtime, body):
    client, _, headers, _ = runtime
    response = client.post(ENDPOINT, headers=headers["staff"], json=body)
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid tool request"}


def test_unknown_tools_cannot_dispatch_a_function(runtime, monkeypatch):
    client, _, headers, _ = runtime
    lookup = Mock(side_effect=AssertionError("must not run"))
    monkeypatch.setattr(registry, "get_source_status", lookup)
    body = client.post(ENDPOINT, headers=headers["staff"], json={**CALL, "name": "execute_sql"}).json()
    assert body["error"]["code"] == "unknown_tool"
    lookup.assert_not_called()


def test_size_and_media_type_limits(runtime, monkeypatch):
    client, _, headers, _ = runtime
    assert client.post(ENDPOINT, headers=headers["staff"], content="{}").status_code == 415
    assert client.post(ENDPOINT, headers={**headers["staff"], "Content-Type": "application/json"},
                       content="{").status_code == 422
    large = {**CALL, "arguments": {"source_id": SOURCE_ID, "text": "x" * 5000}}
    assert client.post(ENDPOINT, headers=headers["staff"], json=large).json()["error"]["code"] == "invalid_arguments"
    large["arguments"]["text"] = "x" * 9000
    assert client.post(ENDPOINT, headers=headers["staff"], json=large).status_code == 413


@pytest.mark.parametrize("change,value", [("is_active", False), ("role", "admin")])
def test_user_revocation_and_role_changes_take_effect_on_next_call(runtime, change, value):
    client, sessions, headers, _ = runtime
    with sessions.begin() as db:
        db.get(SourceRegistration, SOURCE_ID).visibility = "admin"
        setattr(db.get(User, 1), change, value)
    response = client.post(ENDPOINT, headers=headers["staff"], json=CALL)
    assert response.status_code == (401 if change == "is_active" else 200)
    if change == "role":
        assert response.json()["ok"] is True


@pytest.mark.parametrize("role,is_active", [("public", True), ("unknown", True), ("admin", False)])
def test_internal_dispatch_also_checks_actor(runtime, monkeypatch, role, is_active):
    _, sessions, _, _ = runtime
    lookup = Mock(side_effect=AssertionError("must not run"))
    monkeypatch.setattr(registry, "get_source_status", lookup)
    with sessions() as db:
        result = registry.execute_tool(ToolInvocation.model_validate(CALL), db, SimpleNamespace(role=role, is_active=is_active))
    assert result.error.code == "permission_denied"
    lookup.assert_not_called()


@pytest.mark.parametrize("failure,code", [
    (SQLAlchemyError("password=secret"), "tool_unavailable"),
    (RuntimeError("private content and secret"), "tool_unavailable"),
    (DBAPIError("private sql", {}, SimpleNamespace(sqlstate="57014")), "tool_timeout"),
    (DBAPIError("private sql", {}, SimpleNamespace(sqlstate="55P03")), "tool_timeout"),
    (DBAPIError("private sql", {}, SimpleNamespace(sqlstate="08006")), "tool_unavailable"),
])
def test_failures_have_safe_structured_results_and_redacted_logs(runtime, monkeypatch, caplog, failure, code):
    client, _, headers, _ = runtime
    monkeypatch.setattr(registry, "get_source_status", Mock(side_effect=failure))
    with caplog.at_level(logging.INFO, logger="app.tools.registry"):
        response = client.post(ENDPOINT, headers=headers["staff"], json=CALL)
    assert response.status_code == 200 and response.json()["error"]["code"] == code
    for text in (response.text, caplog.text):
        assert "secret" not in text and "private" not in text and SOURCE_ID not in text
    assert "duration_ms=" in caplog.text and "name=get_source_status" in caplog.text


def test_invalid_handler_result_is_not_returned(runtime, monkeypatch):
    client, _, headers, _ = runtime
    monkeypatch.setattr(registry, "get_source_status", lambda *args: {"password": "secret"})
    response = client.post(ENDPOINT, headers=headers["staff"], json=CALL)
    assert response.json()["error"]["code"] == "invalid_result"
    assert "secret" not in response.text


def test_postgresql_lookup_sets_transaction_local_time_limits_before_read():
    db = Mock()
    db.no_autoflush = Mock()
    db.no_autoflush.__enter__ = Mock()
    db.no_autoflush.__exit__ = Mock(return_value=False)
    db.get_bind.return_value.dialect.name = "postgresql"
    db.scalar.return_value = None
    assert get_source_status(db, SimpleNamespace(role="staff", is_active=True), SOURCE_ID) is None
    assert [str(call.args[0]) for call in db.execute.call_args_list] == [
        "SET LOCAL statement_timeout = '2s'", "SET LOCAL lock_timeout = '1s'",
    ]
    db.scalar.assert_called_once()
    db.commit.assert_not_called()


def test_direct_service_denies_unrecognized_roles_before_query():
    db = Mock()
    assert get_source_status(db, SimpleNamespace(role="public", is_active=True), SOURCE_ID) is None
    db.scalar.assert_not_called()


def test_openapi_describes_strict_request_and_structured_results():
    schema = app.openapi()["paths"][ENDPOINT]["post"]
    request = schema["requestBody"]["content"]["application/json"]["schema"]
    assert request["additionalProperties"] is False
    assert set(request["required"]) == {"name", "arguments"}
    assert schema["security"] == [{"HTTPBearer": []}]
