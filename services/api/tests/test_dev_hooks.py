import asyncio
import os

import pytest
from fastapi.testclient import TestClient

from tests.support import database_url, new_user

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="Set TEST_DATABASE_URL for real Postgres"
)


def dev_client(user: str) -> TestClient:
    from app.main import create_app
    from app.providers.fake import FakeProvider
    from app.settings import Settings

    settings = Settings(_env_file=None, database_url=database_url(), app_env="development")
    app = create_app(settings, provider=FakeProvider(deltas=["baseline"]))

    @app.get("/v1/_test/probe-supervisor-provider")
    def probe() -> dict[str, str]:
        return {"kind": type(app.state.supervisor._provider).__name__}  # noqa: SLF001

    return TestClient(app, headers={"X-Dev-User": user})


def test_fake_plan_endpoint_replaces_the_provider_in_development() -> None:
    with dev_client(new_user("devplan")) as client:
        assert client.get("/v1/_test/probe-supervisor-provider").json() == {"kind": "FakeProvider"}
        response = client.post(
            "/v1/_test/fake-plan",
            json={"steps": [{"deltas": ["a", "b"], "delay_seconds": 0.0}]},
        )
        assert response.status_code == 200
        assert response.json() == {"status": "planned", "steps": 1}
        assert client.get("/v1/_test/probe-supervisor-provider").json() == {
            "kind": "PlannedFakeProvider"
        }

        bad = client.post("/v1/_test/fake-plan", json={"steps": []})
        assert bad.status_code == 400
        assert bad.json()["code"] == "validation_failed"


def test_fake_plan_endpoint_is_hidden_outside_development() -> None:
    from app.api.auth import Actor, require_actor
    from app.main import create_app
    from app.settings import Settings

    settings = Settings(
        _env_file=None,
        app_env="staging",
        database_url="postgresql+asyncpg://a:b@127.0.0.1:1/db",
        xai_api_key="test-key",
        auth_jwt_issuer="https://auth.example.test",
        auth_jwt_audience="copilot",
        auth_jwt_jwks_url="https://auth.example.test/jwks.json",
    )
    app = create_app(settings)
    app.dependency_overrides[require_actor] = lambda: Actor(user_id="tester")
    with TestClient(app) as client:
        response = client.post("/v1/_test/fake-plan", json={"steps": [{"deltas": ["x"]}]})
    assert response.status_code == 404


def test_planned_provider_streams_through_the_supervisor_boundary() -> None:
    from app.providers.fake import PlannedFakeProvider
    from app.providers.protocol import CancelSignal

    async def scenario() -> None:
        from app.providers.fake import planned_provider_from_steps

        provider = planned_provider_from_steps([{"deltas": ["he", "llo"], "finish_reason": "stop"}])
        assert isinstance(provider, PlannedFakeProvider)
        deltas = [delta async for delta in provider.stream([], signal=CancelSignal())]
        assert "".join(delta.text for delta in deltas) == "hello"

    asyncio.run(scenario())
