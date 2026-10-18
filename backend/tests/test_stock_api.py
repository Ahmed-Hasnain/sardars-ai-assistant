"""Authenticated stock reads, saved answers and fresh follow-ups in isolated SQL."""

import json
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.security import hash_password
from app.db.base import Base
from app.db.models import User
from app.db.products import Product
from app.db.session import get_db
from app.main import app

PASSWORD = "correct horse battery staple"


@pytest.fixture
def runtime():
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions.begin() as db:
        db.add_all([
            User(id=1, email="stock-staff@example.test", role="staff", password_hash=hash_password(PASSWORD)),
            User(id=2, email="stock-admin@example.test", role="admin", password_hash=hash_password(PASSWORD)),
        ])
        common = dict(source_file_name="stock-fixture.csv", source_file_sha256="a" * 64,
                      source_row_kind="variant", status="active")
        db.add_all([
            Product(**common, source_row_number=1, handle="test-mixer", title="Test Mixer",
                    variant_sku="STOCK-1", variant_price=150, variant_inventory_qty=7,
                    visibility="staff"),
            Product(**common, source_row_number=2, handle="sold-out-mixer", title="Sold Out Mixer",
                    variant_sku="STOCK-0", variant_price=120, variant_inventory_qty=0,
                    visibility="staff"),
            Product(**common, source_row_number=3, handle="private-mixer", title="Private Mixer",
                    variant_sku="STOCK-ADMIN", variant_price=200, variant_inventory_qty=13,
                    visibility="admin"),
        ])

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


def login(client: TestClient, email: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def test_authenticated_stream_and_history_reread_stock_after_change(runtime):
    client, sessions = runtime
    assert client.post("/api/v1/chat", json={"message": "Is SKU STOCK-1 in stock?"}).status_code == 401
    staff = login(client, "stock-staff@example.test")
    with patch("app.api.chat.chat_model.chat", side_effect=AssertionError("model must not decide stock")):
        first = client.post("/api/v1/chat/stream", headers=staff,
                            json={"message": "Is SKU STOCK-1 in stock?"})
    assert first.status_code == 200
    complete = next(json.loads(block.split("data: ", 1)[1]) for block in first.text.split("\n\n")
                    if block.startswith("event: complete\n"))
    assert complete["route"] == "product" and complete["model"] is None
    assert "database stock 7 units" in complete["answer"]
    assert complete["product_source"]["current_stock_verified"] is True
    assert complete["product_source"]["external_sync_verified"] is False
    conversation = complete["conversation_id"]

    with sessions.begin() as db:
        db.query(Product).filter(Product.variant_sku == "STOCK-1").update({"variant_inventory_qty": 0})
    second = client.post("/api/v1/chat", headers=staff,
                         json={"message": "What is the stock for SKU STOCK-1?", "conversation_id": conversation})
    assert second.status_code == 200 and second.json()["conversation_id"] == conversation
    assert "database stock 0 units" in second.json()["answer"]
    assert "database stock 7 units" not in second.json()["answer"]
    history = client.get(f"/api/v1/conversations/{conversation}", headers=staff)
    assert history.status_code == 200
    assert [message["role"] for message in history.json()["messages"]] == ["user", "assistant"] * 2
    assert client.get(f"/api/v1/conversations/{conversation}", headers=login(client, "stock-admin@example.test")).status_code == 404


def test_tool_visibility_zero_stock_and_revocation(runtime):
    client, sessions = runtime
    staff = login(client, "stock-staff@example.test")
    admin = login(client, "stock-admin@example.test")
    call = lambda sku: {"name": "get_product_details", "arguments": {"identifier": sku}}
    hidden = client.post("/api/v1/tools/execute", headers=staff, json=call("STOCK-ADMIN"))
    visible = client.post("/api/v1/tools/execute", headers=admin, json=call("STOCK-ADMIN"))
    zero = client.post("/api/v1/tools/execute", headers=staff, json=call("STOCK-0"))
    assert hidden.status_code == visible.status_code == zero.status_code == 200
    assert hidden.json()["error"]["code"] == "product_not_found"
    assert visible.json()["data"]["variants"][0]["stock_quantity"] == 13
    assert zero.json()["data"]["variants"][0]["stock_quantity"] == 0
    assert zero.json()["data"]["inventory_verified"] is True
    with sessions.begin() as db:
        db.get(User, 1).is_active = False
    assert client.post("/api/v1/chat", headers=staff, json={"message": "Stock for SKU STOCK-0?"}).status_code == 401
