from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.main import app

client = TestClient(app)


def test_liveness() -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_with_postgres() -> None:
    response = client.get("/api/v1/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readiness_when_postgres_is_unavailable() -> None:
    with patch(
        "app.api.health.engine.connect",
        side_effect=SQLAlchemyError("database unavailable"),
    ):
        response = client.get("/api/v1/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
