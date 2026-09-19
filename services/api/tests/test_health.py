import os
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings


def test_live_ok_even_without_database():
    settings = Settings(_env_file=None, database_url="postgresql+asyncpg://a:b@127.0.0.1:1/db")
    with TestClient(create_app(settings)) as client:
        response = client.get("/health/live")
        assert response.status_code == 200
        assert response.json() == {"status": "live"}


def test_ready_requires_db_and_does_not_leak_connection_details():
    settings = Settings(_env_file=None, database_url="postgresql+asyncpg://a:secret@127.0.0.1:1/db")
    with TestClient(create_app(settings)) as client:
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.headers["content-type"] == "application/problem+json"
        body = response.json()
        assert body["status"] == "not_ready"
        assert body["database"] == "error"
        assert body["code"] == "service_unavailable"
        assert body["type"] == "https://copilot.local/problems/service_unavailable"
        UUID(body["diagnostic_id"])
        assert "secret" not in response.text
        assert "127.0.0.1" not in response.text


@pytest.mark.integration
@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="Set TEST_DATABASE_URL for real Postgres"
)
def test_ready_with_real_postgres():
    settings = Settings(_env_file=None, database_url=os.environ["TEST_DATABASE_URL"])
    with TestClient(create_app(settings)) as client:
        response = client.get("/health/ready")
        assert response.status_code == 200
        assert response.json() == {"status": "ready", "database": "ok"}


def test_database_authentication_failure_is_not_a_500(monkeypatch):
    from asyncpg import InvalidPasswordError

    app = create_app(Settings(_env_file=None))
    with TestClient(app) as client:

        def rejected_connection(self):
            raise InvalidPasswordError("private database authentication details")

        monkeypatch.setattr(type(app.state.engine), "connect", rejected_connection)
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json()["code"] == "service_unavailable"
        assert "private database" not in response.text
