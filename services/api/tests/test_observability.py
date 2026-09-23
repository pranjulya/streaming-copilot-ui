import asyncio
import logging
import os
import uuid

import pytest
from fastapi.testclient import TestClient

from tests.support import database_url, new_user

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="Set TEST_DATABASE_URL for real Postgres"
)


def observable_client(user: str, provider=None) -> TestClient:
    from app.main import create_app
    from app.providers.fake import FakeProvider
    from app.settings import Settings

    settings = Settings(_env_file=None, database_url=database_url(), app_env="development")
    app = create_app(
        settings, provider=provider if provider is not None else FakeProvider(deltas=["ok"])
    )
    return TestClient(app, headers={"X-Dev-User": user})


def metrics_text(client: TestClient) -> str:
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    return response.text


def test_metrics_expose_request_run_event_and_token_counters() -> None:
    from app.chat.event_writer import Usage
    from app.providers.fake import FakeProvider

    async def scenario() -> None:
        user = new_user("metrics")
        provider = FakeProvider(deltas=["hello"], finish_reason="stop", usage=Usage(9, 4))
        with observable_client(user, provider) as client:
            created = client.post(
                "/v1/conversations",
                json={},
                headers={"Idempotency-Key": str(uuid.uuid4())},
            )
            conversation_id = created.json()["id"]
            with client.stream(
                "POST",
                f"/v1/conversations/{conversation_id}/responses",
                json={"client_message_id": str(uuid.uuid4()), "content": "hi"},
                headers={"Idempotency-Key": str(uuid.uuid4())},
            ) as response:
                b"".join(response.iter_bytes())
            text = metrics_text(client)

        assert "copilot_http_requests_total" in text
        assert 'copilot_events_emitted_total{type="message.delta"}' in text
        assert 'copilot_events_emitted_total{type="response.completed"}' in text
        assert (
            'copilot_runs_terminal_total{error_code="",model="grok-4.6",status="completed"}' in text
        )
        assert 'copilot_tokens_total{direction="input",model="grok-4.6"} 9.0' in text
        assert 'copilot_tokens_total{direction="output",model="grok-4.6"} 4.0' in text

    asyncio.run(scenario())


def test_metric_name_table_is_complete() -> None:
    from app.observability import metrics

    names = {
        "copilot_http_requests_total",
        "copilot_runs_terminal_total",
        "copilot_runs_active",
        "copilot_runs_orphaned_total",
        "copilot_idempotency_hits_total",
        "copilot_events_emitted_total",
        "copilot_stream_bytes_total",
        "copilot_sequence_gaps_total",
        "copilot_content_mismatch_total",
        "copilot_accept_latency_seconds",
        "copilot_provider_first_token_seconds",
        "copilot_service_first_event_seconds",
        "copilot_generation_duration_seconds",
        "copilot_cancel_ack_seconds",
        "copilot_reconnect_catchup_seconds",
        "copilot_db_tx_seconds",
        "copilot_tokens_total",
    }
    from prometheus_client import Counter

    def exported_name(metric: object) -> str:
        name = str(getattr(metric, "_name", ""))
        if isinstance(metric, Counter):
            return f"{name}_total"
        return name

    defined = {
        exported_name(metric)
        for metric in [
            metrics.HTTP_REQUESTS_TOTAL,
            metrics.RUNS_TERMINAL_TOTAL,
            metrics.RUNS_ACTIVE,
            metrics.RUNS_ORPHANED_TOTAL,
            metrics.IDEMPOTENCY_HITS_TOTAL,
            metrics.EVENTS_EMITTED_TOTAL,
            metrics.STREAM_BYTES_TOTAL,
            metrics.SEQUENCE_GAPS_TOTAL,
            metrics.CONTENT_MISMATCH_TOTAL,
            metrics.ACCEPT_LATENCY_SECONDS,
            metrics.PROVIDER_FIRST_TOKEN_SECONDS,
            metrics.SERVICE_FIRST_EVENT_SECONDS,
            metrics.GENERATION_DURATION_SECONDS,
            metrics.CANCEL_ACK_SECONDS,
            metrics.RECONNECT_CATCHUP_SECONDS,
            metrics.DB_TX_SECONDS,
            metrics.TOKENS_TOTAL,
        ]
    }
    assert names == defined


def test_logs_carry_correlation_ids_and_hashed_identity_without_content(caplog) -> None:
    async def scenario() -> None:
        user = new_user("logs")
        secret = "SECRET-PROMPT-CONTENT-MARKER"
        with caplog.at_level(logging.INFO):
            with observable_client(user) as client:
                created = client.post(
                    "/v1/conversations",
                    json={},
                    headers={"Idempotency-Key": str(uuid.uuid4())},
                )
                conversation_id = created.json()["id"]
                with client.stream(
                    "POST",
                    f"/v1/conversations/{conversation_id}/responses",
                    json={"client_message_id": str(uuid.uuid4()), "content": secret},
                    headers={"Idempotency-Key": str(uuid.uuid4())},
                ) as response:
                    b"".join(response.iter_bytes())

        text = caplog.text
        assert "actor_resolved" in text
        assert user not in text
        assert secret not in text
        assert "ok" not in text.split("actor_resolved", 1)[0]

    asyncio.run(scenario())


def test_request_ids_are_echoed_and_unique() -> None:
    with observable_client(new_user("reqids")) as client:
        first = client.get("/health/live")
        second = client.get("/health/live")
    assert first.headers["x-request-id"] != second.headers["x-request-id"]

    with observable_client(new_user("reqids2")) as client:
        echoed = client.get("/health/live", headers={"X-Request-ID": "fixed-id"})
    assert echoed.headers["x-request-id"] == "fixed-id"
