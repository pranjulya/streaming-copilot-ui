import os

import pytest
from fastapi.testclient import TestClient

from tests.support import database_url, new_user

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="Set TEST_DATABASE_URL for real Postgres"
)


def cors_client() -> TestClient:
    from app.main import create_app
    from app.settings import Settings

    settings = Settings(
        _env_file=None,
        database_url=database_url(),
        app_env="development",
        allowed_origins="http://127.0.0.1:3000,https://copilot.example",
    )
    return TestClient(create_app(settings), headers={"X-Dev-User": new_user("cors")})


def test_allowed_origin_is_echoed_with_credentials() -> None:
    with cors_client() as client:
        response = client.options(
            "/v1/conversations",
            headers={
                "Origin": "http://127.0.0.1:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "idempotency-key,content-type",
            },
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "Idempotency-Key" in response.headers["access-control-allow-headers"]


def test_disallowed_origin_receives_no_cors_headers() -> None:
    with cors_client() as client:
        response = client.options(
            "/v1/conversations",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "POST",
            },
        )
    assert "access-control-allow-origin" not in response.headers


def test_wildcard_origins_are_rejected_at_startup() -> None:
    from pydantic import ValidationError

    from app.settings import Settings

    with pytest.raises(ValidationError, match="ALLOWED_ORIGINS"):
        Settings(_env_file=None, allowed_origins="*")
    with pytest.raises(ValidationError, match="ALLOWED_ORIGINS"):
        Settings(_env_file=None, allowed_origins="https://a.example,*")


def test_simple_request_from_allowed_origin_gets_acao() -> None:
    with cors_client() as client:
        response = client.get("/health/live", headers={"Origin": "https://copilot.example"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://copilot.example"
