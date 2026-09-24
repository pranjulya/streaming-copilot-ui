import asyncio
import json
import os
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker

from tests.support import database_url, new_user

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="Set TEST_DATABASE_URL for real Postgres"
)

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"


def validator() -> Draft202012Validator:
    schema = json.loads((CONTRACTS / "stream-events.schema.json").read_text())
    return Draft202012Validator(schema, format_checker=FormatChecker())


def stream_settings(**overrides: object):
    from app.settings import Settings

    values: dict[str, object] = {
        "database_url": database_url(),
        "delta_flush_ms": 5,
        "event_follow_poll_ms": 10,
        "heartbeat_interval_seconds": 30,
        "generation_timeout_seconds": 30,
        "provider_idle_timeout_seconds": 5,
        "lease_seconds": 30,
        "lease_renew_seconds": 2,
        "shutdown_grace_seconds": 1,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def make_app(provider, **settings_overrides: object):
    from app.main import create_app

    return create_app(stream_settings(**settings_overrides), provider=provider)


def api_client(user: str, provider, **settings_overrides: object) -> TestClient:
    return TestClient(make_app(provider, **settings_overrides), headers={"X-Dev-User": user})


def read_ndjson(response) -> tuple[list[dict], str]:
    text = b"".join(response.iter_bytes()).decode("utf-8")
    assert text.endswith("\n"), "NDJSON responses end each line with a newline"
    lines = [json.loads(line) for line in text.split("\n")[:-1]]
    return lines, text


def create_conversation(client: TestClient) -> str:
    response = client.post(
        "/v1/conversations", json={}, headers={"Idempotency-Key": str(uuid.uuid4())}
    )
    assert response.status_code == 201
    return str(response.json()["id"])


def test_create_and_stream_returns_schema_valid_ndjson() -> None:
    from app.chat.event_writer import Usage
    from app.providers.fake import FakeProvider

    async def scenario() -> None:
        user = new_user("stream")
        provider = FakeProvider(
            deltas=["Back", "pressure"], finish_reason="stop", usage=Usage(2, 3)
        )
        with api_client(user, provider) as client:
            conversation_id = create_conversation(client)
            client_message_id = str(uuid.uuid4())
            body = {"client_message_id": client_message_id, "content": "Explain backpressure"}
            key = str(uuid.uuid4())
            with client.stream(
                "POST",
                f"/v1/conversations/{conversation_id}/responses",
                json=body,
                headers={"Idempotency-Key": key},
            ) as response:
                assert response.status_code == 200
                assert response.headers["content-type"] == "application/x-ndjson; charset=utf-8"
                assert response.headers["cache-control"] == "no-cache, no-store"
                assert response.headers["x-accel-buffering"] == "no"
                lines, text = read_ndjson(response)

            event_validator = validator()
            for line in lines:
                event_validator.validate(line)
            types = [line["type"] for line in lines]
            assert types[0] == "response.started"
            assert types[-1] == "response.completed"
            assert "message.delta" in types
            deltas = "".join(
                str(line["data"]["delta"]) for line in lines if line["type"] == "message.delta"
            )
            assert deltas == "Backpressure"
            assert [line["sequence"] for line in lines] == list(range(1, len(lines) + 1))
            run_id = str(lines[0]["run_id"])

            detail = client.get(f"/v1/conversations/{conversation_id}").json()
            assert detail["active_run"] is None
            assistant = [m for m in detail["messages"]["items"] if m["role"] == "assistant"]
            assert assistant[-1]["content"] == "Backpressure"
            assert assistant[-1]["status"] == "complete"

            with client.stream(
                "POST",
                f"/v1/conversations/{conversation_id}/responses",
                json=body,
                headers={"Idempotency-Key": key},
            ) as replay:
                assert replay.status_code == 200
                replay_lines, _ = read_ndjson(replay)
            assert [line["type"] for line in replay_lines] == types
            assert [line["sequence"] for line in replay_lines] == [
                line["sequence"] for line in lines
            ]
            assert {line["run_id"] for line in replay_lines} == {run_id}

            with client.stream(
                "POST",
                f"/v1/response-runs/{run_id}/stream",
                json={"after_sequence": 2},
            ) as follower:
                assert follower.status_code == 200
                follow_lines, _ = read_ndjson(follower)
            assert follow_lines[0]["sequence"] == 3
            assert [line["type"] for line in follow_lines] == types[2:]

        del text

    asyncio.run(scenario())


def test_create_and_stream_schema_valid_when_provider_omits_usage() -> None:
    from app.providers.fake import FakeProvider

    async def scenario() -> None:
        user = new_user("stream-nousage")
        provider = FakeProvider(deltas=["ok"], finish_reason="stop", usage=None)
        with api_client(user, provider) as client:
            conversation_id = create_conversation(client)
            with client.stream(
                "POST",
                f"/v1/conversations/{conversation_id}/responses",
                json={"client_message_id": str(uuid.uuid4()), "content": "hi"},
                headers={"Idempotency-Key": str(uuid.uuid4())},
            ) as response:
                assert response.status_code == 200
                lines, _ = read_ndjson(response)
        event_validator = validator()
        for line in lines:
            event_validator.validate(line)
        completed = [line for line in lines if line["type"] == "response.completed"]
        assert completed[-1]["data"]["usage"] == {"input_tokens": 0, "output_tokens": 0}

    asyncio.run(scenario())


def test_retry_and_regenerate_stream_new_run_and_require_idempotency_key() -> None:
    from app.providers.fake import FakeProvider
    from app.providers.protocol import ProviderError

    async def scenario() -> None:
        user = new_user("stream-retry")
        provider = FakeProvider(
            deltas=[],
            fail_after=0,
            failure=ProviderError(code="provider_unavailable", message="down"),
        )
        with api_client(user, provider) as client:
            conversation_id = create_conversation(client)
            with client.stream(
                "POST",
                f"/v1/conversations/{conversation_id}/responses",
                json={"client_message_id": str(uuid.uuid4()), "content": "Question"},
                headers={"Idempotency-Key": str(uuid.uuid4())},
            ) as response:
                assert response.status_code == 200
                first_lines, _ = read_ndjson(response)
            assert first_lines[-1]["type"] == "response.failed"
            run_id = str(first_lines[0]["run_id"])

            missing_key = client.post(f"/v1/response-runs/{run_id}/retry", json={})
            assert missing_key.status_code == 400
            assert missing_key.json()["code"] == "validation_failed"

            with client.stream(
                "POST",
                f"/v1/response-runs/{run_id}/retry",
                json={},
                headers={"Idempotency-Key": str(uuid.uuid4())},
            ) as retried:
                assert retried.status_code == 200
                assert retried.headers["content-type"] == "application/x-ndjson; charset=utf-8"
                retry_lines, _ = read_ndjson(retried)
            assert retry_lines[0]["type"] == "response.started"
            assert retry_lines[0]["data"]["attempt"] == 2
            assert retry_lines[0]["run_id"] != run_id
            assert retry_lines[-1]["type"] == "response.failed"

            detail = client.get(f"/v1/conversations/{conversation_id}").json()
            user_message_id = detail["messages"]["items"][0]["id"]

            missing_key = client.post(f"/v1/messages/{user_message_id}/regenerations", json={})
            assert missing_key.status_code == 400

            with client.stream(
                "POST",
                f"/v1/messages/{user_message_id}/regenerations",
                json={},
                headers={"Idempotency-Key": str(uuid.uuid4())},
            ) as regenerated:
                assert regenerated.status_code == 200
                assert regenerated.headers["content-type"] == "application/x-ndjson; charset=utf-8"
                regenerate_lines, _ = read_ndjson(regenerated)
            assert regenerate_lines[0]["type"] == "response.started"
            assert regenerate_lines[-1]["type"] == "response.failed"

    asyncio.run(scenario())


def test_stream_journey_does_not_log_content(caplog) -> None:
    import logging

    from app.providers.fake import FakeProvider

    async def scenario() -> None:
        user = new_user("stream-logs")
        secret = "SECRET-PROMPT-CONTENT"
        provider = FakeProvider(deltas=["reply text"], finish_reason="stop")
        with caplog.at_level(logging.DEBUG):
            with api_client(user, provider) as client:
                conversation_id = create_conversation(client)
                with client.stream(
                    "POST",
                    f"/v1/conversations/{conversation_id}/responses",
                    json={"client_message_id": str(uuid.uuid4()), "content": secret},
                    headers={"Idempotency-Key": str(uuid.uuid4())},
                ) as response:
                    lines, _ = read_ndjson(response)
                assert lines[-1]["type"] == "response.completed"
        assert secret not in caplog.text

    asyncio.run(scenario())
