from unittest.mock import AsyncMock, patch
from hashlib import sha256

from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.security import hash_password, token_hash, verify_password
from app.api.rate_limits import LOGIN_ACCOUNT_LIMITER, LOGIN_IP_LIMITER
from app.auth.create_user import main as create_user_main
from app.auth.reset_password import main as reset_password_main
from app.db.base import Base
from app.db.models import LoginSession, SourceRegistration, User
from app.db.session import get_db
from app.llm.base import ChatResult
from app.main import app


PASSWORD = "correct horse battery staple"
SOURCE_URL = "https://sardarandco.com/pages/about-us"
SOURCE_ID = sha256(SOURCE_URL.encode()).hexdigest()
CONTENT_SHA256 = sha256(b"test source content").hexdigest()


@pytest.fixture
def local_app():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)

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


def _create_user(sessions, email: str, role: str = "staff") -> User:
    with sessions() as db:
        user = User(email=email, password_hash=hash_password(PASSWORD), role=role)
        db.add(user)
        db.commit()
        db.refresh(user)
        db.expunge(user)
    return user


def _login(client: TestClient, email: str) -> str:
    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _brand_point() -> dict:
    return {"payload": {
        "visibility": "public", "review_status": "approved", "prototype_only": False,
        "source_id": SOURCE_ID, "source_type": "pages", "title": "About Us", "url": SOURCE_URL,
        "content_sha256": CONTENT_SHA256,
        "text": "Sardars mentions brands like Bongio, Scarabeo and Grohe.",
    }}


def _register_brand_source(sessions, *, visibility: str = "public", is_active: bool = True) -> None:
    with sessions() as db:
        db.add(SourceRegistration(
            source_id=SOURCE_ID, url=SOURCE_URL, source_type="pages",
            content_sha256=CONTENT_SHA256,
            visibility=visibility, is_active=is_active,
            authorization_basis="test_source_authorization",
        ))
        db.commit()


def test_passwords_are_salted_and_verified() -> None:
    first = hash_password(PASSWORD)
    second = hash_password(PASSWORD)
    assert first != second
    assert PASSWORD not in first
    assert verify_password(PASSWORD, first)
    assert not verify_password("wrong password", first)
    assert not verify_password(PASSWORD, None)


def test_login_is_revocable_and_stores_only_a_token_hash(local_app) -> None:
    client, sessions = local_app
    user = _create_user(sessions, "staff@example.com")
    assert client.post("/api/v1/auth/login", json={
        "email": user.email, "password": "wrong password",
    }).status_code == 401

    token = _login(client, "STAFF@EXAMPLE.COM")
    with sessions() as db:
        saved = db.scalar(select(LoginSession))
        assert saved is not None
        assert saved.token_hash == token_hash(token)
        assert token != saved.token_hash

    assert client.get("/api/v1/auth/me", headers=_headers(token)).json()["role"] == "staff"
    assert client.post("/api/v1/auth/logout", headers=_headers(token)).status_code == 204
    assert client.get("/api/v1/auth/me", headers=_headers(token)).status_code == 401


def test_login_attempts_are_bounded_per_account_and_ip(local_app, monkeypatch):
    client, sessions = local_app
    _create_user(sessions, "staff@example.com")
    monkeypatch.setattr(LOGIN_ACCOUNT_LIMITER, "limit", 2)
    monkeypatch.setattr(LOGIN_IP_LIMITER, "limit", 4)
    wrong = {"email": "staff@example.com", "password": "wrong"}
    assert client.post("/api/v1/auth/login", json=wrong).status_code == 401
    assert client.post("/api/v1/auth/login", json=wrong).status_code == 401
    blocked = client.post("/api/v1/auth/login", json={**wrong, "password": PASSWORD})
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1
    assert blocked.json() == {"detail": "Too many requests"}
    # Changing email cannot evade the separate socket-peer limit.
    assert client.post("/api/v1/auth/login", json={**wrong, "email": "other@example.com"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={**wrong, "email": "third@example.com"}).status_code == 429


def test_staff_cannot_list_users_but_admin_can(local_app) -> None:
    client, sessions = local_app
    _create_user(sessions, "staff@example.com")
    _create_user(sessions, "admin@example.com", role="admin")

    staff_token = _login(client, "staff@example.com")
    admin_token = _login(client, "admin@example.com")
    assert client.get("/api/v1/admin/users", headers=_headers(staff_token)).status_code == 403
    response = client.get("/api/v1/admin/users", headers=_headers(admin_token))
    assert response.status_code == 200
    assert {item["email"] for item in response.json()} == {
        "staff@example.com", "admin@example.com",
    }
    assert all("password_hash" not in item for item in response.json())


def test_disabled_user_loses_access_immediately(local_app) -> None:
    client, sessions = local_app
    user = _create_user(sessions, "staff@example.com")
    token = _login(client, user.email)
    with sessions() as db:
        saved = db.get(User, user.id)
        saved.is_active = False
        db.commit()

    assert client.get("/api/v1/auth/me", headers=_headers(token)).status_code == 401


def test_expired_session_and_role_changes_take_effect_immediately(local_app) -> None:
    client, sessions = local_app
    user = _create_user(sessions, "staff@example.com")
    token = _login(client, user.email)
    with sessions() as db:
        db.get(User, user.id).role = "admin"
        db.commit()
    assert client.get("/api/v1/admin/users", headers=_headers(token)).status_code == 200

    with sessions() as db:
        db.get(LoginSession, token_hash(token)).expires_at_epoch = 0
        db.commit()
    assert client.get("/api/v1/auth/me", headers=_headers(token)).status_code == 401


def test_create_user_command_requires_first_admin_and_prompts_for_password(
    local_app, monkeypatch
) -> None:
    _client, sessions = local_app
    monkeypatch.setattr("app.auth.create_user.SessionLocal", sessions)
    monkeypatch.setattr("app.auth.create_user.getpass", lambda _prompt: PASSWORD)
    monkeypatch.setattr(
        "sys.argv", ["create_user", "--email", "staff@example.com", "--role", "staff"]
    )
    with pytest.raises(SystemExit, match="first user must be an admin"):
        create_user_main()

    monkeypatch.setattr(
        "sys.argv", ["create_user", "--email", "Admin@Example.com", "--role", "admin"]
    )
    create_user_main()
    with sessions() as db:
        admin = db.scalar(select(User))
        assert admin.email == "admin@example.com"
        assert admin.role == "admin"
        assert verify_password(PASSWORD, admin.password_hash)


def test_reset_password_revokes_existing_sessions(local_app, monkeypatch) -> None:
    client, sessions = local_app
    user = _create_user(sessions, "admin@example.com", role="admin")
    old_token = _login(client, user.email)
    new_password = "new private password 123"
    monkeypatch.setattr("app.auth.reset_password.SessionLocal", sessions)
    monkeypatch.setattr("app.auth.reset_password.getpass", lambda _prompt: new_password)
    monkeypatch.setattr(
        "sys.argv", ["reset_password", "--email", "ADMIN@EXAMPLE.COM"]
    )

    reset_password_main()

    assert client.get("/api/v1/auth/me", headers=_headers(old_token)).status_code == 401
    assert client.post("/api/v1/auth/login", json={
        "email": user.email, "password": PASSWORD,
    }).status_code == 401
    assert client.post("/api/v1/auth/login", json={
        "email": user.email, "password": new_password,
    }).status_code == 200
    with sessions() as db:
        assert verify_password(new_password, db.get(User, user.id).password_hash)


def test_reset_password_rejects_mismatch_without_revoking_sessions(local_app, monkeypatch) -> None:
    client, sessions = local_app
    user = _create_user(sessions, "admin@example.com", role="admin")
    token = _login(client, user.email)
    replies = iter(["new private password 123", "different password 123"])
    monkeypatch.setattr("app.auth.reset_password.SessionLocal", sessions)
    monkeypatch.setattr("app.auth.reset_password.getpass", lambda _prompt: next(replies))
    monkeypatch.setattr(
        "sys.argv", ["reset_password", "--email", user.email]
    )

    with pytest.raises(SystemExit, match="Passwords do not match"):
        reset_password_main()

    assert client.get("/api/v1/auth/me", headers=_headers(token)).status_code == 200


def test_ask_checks_auth_before_retrieval_and_returns_citations(local_app) -> None:
    client, sessions = local_app
    _create_user(sessions, "staff@example.com")
    _register_brand_source(sessions)
    with patch("app.services.company_answer.search_for_role") as search:
        assert client.post("/api/v1/ask", json={"message": "Which brands?"}).status_code == 401
        search.assert_not_called()

    token = _login(client, "staff@example.com")
    with (
        patch("app.services.company_answer.search_for_role", return_value=[_brand_point()]),
        patch("app.api.ask.answer_model.chat", new_callable=AsyncMock) as chat,
    ):
        chat.return_value = ChatResult(
            "Sardars mentions Bongio, Scarabeo and Grohe. [1]", "test", None, None, None
        )
        response = client.post(
            "/api/v1/ask", json={"message": "Which brands?"}, headers=_headers(token)
        )

    assert response.status_code == 200
    assert response.json()["sources"] == [{
        "number": 1, "source_id": SOURCE_ID, "title": "About Us",
        "url": SOURCE_URL, "fetched_at": None,
        "content_derivation": None, "original_content_sha256": None,
    }]
    assert "Bongio" in response.json()["answer"]


def test_ask_ignores_unregistered_or_disabled_source(local_app) -> None:
    client, sessions = local_app
    _create_user(sessions, "staff@example.com")
    token = _login(client, "staff@example.com")
    with (
        patch("app.services.company_answer.search_for_role", return_value=[_brand_point()]),
        patch("app.api.ask.answer_model.chat", new_callable=AsyncMock) as chat,
    ):
        response = client.post(
            "/api/v1/ask", json={"message": "Which brands?"}, headers=_headers(token)
        )
        assert response.status_code == 200
        assert response.json()["sources"] == []
        chat.assert_not_called()

        _register_brand_source(sessions, is_active=False)
        response = client.post(
            "/api/v1/ask", json={"message": "Which brands?"}, headers=_headers(token)
        )
        assert response.status_code == 200
        assert response.json()["sources"] == []
        chat.assert_not_called()


def test_chat_requires_auth_and_ask_hides_retrieval_failures(local_app) -> None:
    client, sessions = local_app
    _create_user(sessions, "staff@example.com")
    assert client.post("/api/v1/chat", json={"message": "Hello"}).status_code == 401
    token = _login(client, "staff@example.com")
    with patch("app.services.company_answer.search_for_role", side_effect=httpx.ConnectError("down")):
        response = client.post(
            "/api/v1/ask", json={"message": "Which brands?"}, headers=_headers(token)
        )
    assert response.status_code == 503
    assert response.json() == {"detail": "Answer service unavailable"}
