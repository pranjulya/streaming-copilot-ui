import asyncio
import json
import os
import uuid

import pytest
from fastapi.testclient import TestClient

from tests.support import database_url, new_user

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="Set TEST_DATABASE_URL for real Postgres"
)


def limited_client(user: str, **overrides: object) -> TestClient:
    from app.main import create_app
    from app.providers.fake import FakeProvider
    from app.settings import Settings

    values: dict[str, object] = {
        "database_url": database_url(),
        "app_env": "development",
        "create_response_per_minute": 2,
        "max_request_bytes": 256,
    }
    values.update(overrides)
    settings = Settings(_env_file=None, **values)  # type: ignore[arg-type]
    app = create_app(settings, provider=FakeProvider(deltas=["ok"]))
    return TestClient(app, headers={"X-Dev-User": user})


def create_conversation(client: TestClient) -> str:
    response = client.post(
        "/v1/conversations", json={}, headers={"Idempotency-Key": str(uuid.uuid4())}
    )
    assert response.status_code == 201
    return str(response.json()["id"])


def send(client: TestClient, conversation_id: str):
    return client.post(
        f"/v1/conversations/{conversation_id}/responses",
        json={"client_message_id": str(uuid.uuid4()), "content": "hello"},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )


def test_send_rate_limit_returns_429_with_headers() -> None:
    async def scenario() -> None:
        with limited_client(new_user("ratelimit")) as client:
            first = create_conversation(client)
            second = create_conversation(client)
            with client.stream(
                "POST",
                f"/v1/conversations/{first}/responses",
                json={"client_message_id": str(uuid.uuid4()), "content": "one"},
                headers={"Idempotency-Key": str(uuid.uuid4())},
            ) as response:
                b"".join(response.iter_bytes())
            with client.stream(
                "POST",
                f"/v1/conversations/{second}/responses",
                json={"client_message_id": str(uuid.uuid4()), "content": "two"},
                headers={"Idempotency-Key": str(uuid.uuid4())},
            ) as response:
                b"".join(response.iter_bytes())

            third = send(client, first)
            assert third.status_code == 429
            assert third.headers["content-type"] == "application/problem+json"
            body = third.json()
            assert body["code"] == "rate_limited"
            assert int(third.headers["retry-after"]) >= 1
            assert third.headers["x-ratelimit-limit"] == "2"
            assert third.headers["x-ratelimit-remaining"] == "0"
            assert third.headers["x-ratelimit-policy"] == "user;w=60"

    asyncio.run(scenario())


def test_rate_limits_are_per_user() -> None:
    async def scenario() -> None:
        with limited_client(new_user("limit-a")) as client_a:
            conversation = create_conversation(client_a)
            with client_a.stream(
                "POST",
                f"/v1/conversations/{conversation}/responses",
                json={"client_message_id": str(uuid.uuid4()), "content": "one"},
                headers={"Idempotency-Key": str(uuid.uuid4())},
            ) as response:
                b"".join(response.iter_bytes())
            with client_a.stream(
                "POST",
                f"/v1/conversations/{conversation}/responses",
                json={"client_message_id": str(uuid.uuid4()), "content": "two"},
                headers={"Idempotency-Key": str(uuid.uuid4())},
            ) as response:
                b"".join(response.iter_bytes())
            limited = send(client_a, conversation)
            assert limited.status_code == 429

        with limited_client(new_user("limit-b")) as client_b:
            conversation_b = create_conversation(client_b)
            allowed = client_b.post(
                f"/v1/conversations/{conversation_b}/responses",
                json={"client_message_id": str(uuid.uuid4()), "content": "hi"},
                headers={"Idempotency-Key": str(uuid.uuid4())},
            )
            assert allowed.status_code == 200
            allowed.close()

    asyncio.run(scenario())


def test_oversized_bodies_are_413_on_rest_and_streaming_routes() -> None:
    async def scenario() -> None:
        with limited_client(new_user("bounds")) as client:
            filler = "x" * 400
            rest = client.post(
                "/v1/conversations",
                json={"title": filler},
                headers={"Idempotency-Key": str(uuid.uuid4())},
            )
            assert rest.status_code == 413
            assert rest.json()["code"] == "payload_too_large"

            conversation = create_conversation(client)
            streaming = client.post(
                f"/v1/conversations/{conversation}/responses",
                json={"client_message_id": str(uuid.uuid4()), "content": filler},
                headers={"Idempotency-Key": str(uuid.uuid4())},
            )
            assert streaming.status_code == 413
            assert streaming.json()["code"] == "payload_too_large"

            patch = client.patch(
                f"/v1/conversations/{conversation}",
                json={"title": filler},
                headers={"Idempotency-Key": str(uuid.uuid4())},
            )
            assert patch.status_code == 413

    asyncio.run(scenario())


def test_oversized_json_is_rejected_even_when_it_would_be_valid() -> None:
    async def scenario() -> None:
        with limited_client(new_user("bounds2"), max_request_bytes=64) as client:
            response = client.post(
                "/v1/conversations",
                content=json.dumps({"title": "tiny"}),
                headers={
                    "content-type": "application/json",
                    "Idempotency-Key": str(uuid.uuid4()),
                },
            )
            assert response.status_code == 201

            big = client.post(
                "/v1/conversations",
                content=json.dumps({"title": "y" * 200}),
                headers={
                    "content-type": "application/json",
                    "Idempotency-Key": str(uuid.uuid4()),
                },
            )
            assert big.status_code == 413

    asyncio.run(scenario())


def test_content_length_header_is_rejected_before_the_body_is_read() -> None:
    from app.api.body_limit import RequestBodyLimitMiddleware

    async def inner(scope, receive, send):  # type: ignore[no-untyped-def]
        while True:
            message = await receive()
            if not message.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def scenario() -> None:
        app = RequestBodyLimitMiddleware(inner, max_bytes=32)
        sent: list[dict[str, object]] = []

        async def receive() -> dict[str, object]:
            raise AssertionError("body must not be read when Content-Length exceeds the bound")

        async def send(message: dict[str, object]) -> None:
            sent.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "method": "POST",
            "path": "/v1/conversations",
            "headers": [(b"content-length", b"10000")],
        }
        await app(scope, receive, send)
        assert sent[0]["status"] == 413

    asyncio.run(scenario())


def test_idle_rate_limit_buckets_are_evicted() -> None:
    from app.api.rate_limit import UserRateLimiter

    limiter = UserRateLimiter(per_minute=2, window_seconds=1.0)
    limiter.check("stale-user")
    limiter._events["stale-user"].clear()
    limiter.check("fresh-user")
    assert "stale-user" not in limiter._events
    assert "fresh-user" in limiter._events


def test_low_quota_mutating_response_carries_rate_limit_headers() -> None:
    async def scenario() -> None:
        with limited_client(new_user("lowquota")) as client:
            conversation = create_conversation(client)
            with client.stream(
                "POST",
                f"/v1/conversations/{conversation}/responses",
                json={"client_message_id": str(uuid.uuid4()), "content": "one"},
                headers={"Idempotency-Key": str(uuid.uuid4())},
            ) as response:
                assert response.status_code == 200
                assert response.headers["x-ratelimit-limit"] == "2"
                assert response.headers["x-ratelimit-remaining"] == "1"
                assert response.headers["x-ratelimit-policy"] == "user;w=60"
                b"".join(response.iter_bytes())

    asyncio.run(scenario())


def test_high_quota_mutating_response_omits_rate_limit_headers() -> None:
    async def scenario() -> None:
        with limited_client(new_user("highquota"), create_response_per_minute=20) as client:
            conversation = create_conversation(client)
            with client.stream(
                "POST",
                f"/v1/conversations/{conversation}/responses",
                json={"client_message_id": str(uuid.uuid4()), "content": "one"},
                headers={"Idempotency-Key": str(uuid.uuid4())},
            ) as response:
                assert response.status_code == 200
                assert "x-ratelimit-limit" not in response.headers
                b"".join(response.iter_bytes())

    asyncio.run(scenario())


def test_dev_fake_plan_body_is_bounded() -> None:
    async def scenario() -> None:
        with limited_client(new_user("fakeplan")) as client:
            oversized = client.post(
                "/v1/_test/fake-plan",
                content=json.dumps({"steps": [{"deltas": ["x" * 400]}]}),
                headers={"content-type": "application/json"},
            )
            assert oversized.status_code == 413
            assert oversized.json()["code"] == "payload_too_large"

            accepted = client.post(
                "/v1/_test/fake-plan",
                content=json.dumps({"steps": [{"deltas": ["ok"]}]}),
                headers={"content-type": "application/json"},
            )
            assert accepted.status_code == 200
            assert accepted.json()["status"] == "planned"

    asyncio.run(scenario())
