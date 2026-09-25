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
    from prometheus_client import Counter, Gauge, Histogram

    from app.observability import metrics

    exported_types = {
        "copilot_http_requests_total": Counter,
        "copilot_runs_terminal_total": Counter,
        "copilot_runs_active": Gauge,
        "copilot_runs_orphaned_total": Counter,
        "copilot_idempotency_hits_total": Counter,
        "copilot_events_emitted_total": Counter,
        "copilot_stream_bytes_total": Counter,
        "copilot_sequence_gaps_total": Counter,
        "copilot_content_mismatch_total": Counter,
        "copilot_accept_latency_seconds": Histogram,
        "copilot_provider_first_token_seconds": Histogram,
        "copilot_service_first_event_seconds": Histogram,
        "copilot_generation_duration_seconds": Histogram,
        "copilot_cancel_ack_seconds": Histogram,
        "copilot_reconnect_catchup_seconds": Histogram,
        "copilot_db_tx_seconds": Histogram,
        "copilot_tokens_total": Counter,
    }

    def exported_name(metric: object) -> str:
        name = str(getattr(metric, "_name", ""))
        if isinstance(metric, Counter):
            return f"{name}_total"
        return name

    defined = {
        exported_name(metric): type(metric)
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
    assert defined == exported_types


def _declared_series() -> set[str]:
    from prometheus_client import Counter

    from app.observability import metrics

    def exported_name(metric: object) -> str:
        name = str(getattr(metric, "_name", ""))
        return f"{name}_total" if isinstance(metric, Counter) else name

    return {
        exported_name(metric)
        for metric in (
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
        )
    }


# Every series declared in docs/observability.md §3 is classified here: it either has an
# honest call site on this branch (WIRED_SERIES, each asserted to move by the scenario
# tests below) or none (NOT_EMITTING_SERIES, documented as declared-but-not-emitting).
# `copilot_content_mismatch_total` has no honest call site: nothing on this branch compares
# a stream's final content against canonical storage, so it stays declared but at zero.
WIRED_SERIES = {
    "copilot_http_requests_total",
    "copilot_runs_terminal_total",
    "copilot_runs_active",
    "copilot_runs_orphaned_total",
    "copilot_idempotency_hits_total",
    "copilot_events_emitted_total",
    "copilot_stream_bytes_total",
    "copilot_sequence_gaps_total",
    "copilot_accept_latency_seconds",
    "copilot_provider_first_token_seconds",
    "copilot_service_first_event_seconds",
    "copilot_generation_duration_seconds",
    "copilot_cancel_ack_seconds",
    "copilot_reconnect_catchup_seconds",
    "copilot_db_tx_seconds",
    "copilot_tokens_total",
}
NOT_EMITTING_SERIES = {"copilot_content_mismatch_total"}


def test_every_declared_series_is_wired_or_documented_not_emitting() -> None:
    assert WIRED_SERIES.isdisjoint(NOT_EMITTING_SERIES)
    # A new series must be classified here (and then either wired or documented), so this
    # fails when the table grows without an honest call site or an explicit exemption.
    assert WIRED_SERIES | NOT_EMITTING_SERIES == _declared_series()


def _metric_value(text: str, sample: str) -> float:
    """Value of one Prometheus sample (name plus exact label set), or 0.0 if absent."""
    prefix = f"{sample} "
    for line in text.splitlines():
        if line.startswith(prefix):
            return float(line[len(prefix) :].split()[0])
    return 0.0


def _delta(after: str, before: str, sample: str) -> float:
    return _metric_value(after, sample) - _metric_value(before, sample)


def _assert_moves(after: str, before: str, sample: str) -> None:
    """Fail when a wired series records no new observation between two scrapes."""
    assert _delta(after, before, sample) > 0, f"{sample} never observed"


# Series with an honest call site on this branch; the scenario tests below assert
# each one moves. Any wired series that stops being observed fails its assertion.
def test_streamed_turn_observes_its_wired_series() -> None:
    from app.providers.fake import FakeProvider

    async def scenario() -> None:
        user = new_user("wired")
        provider = FakeProvider(deltas=["hello ", "world"], finish_reason="stop")
        with observable_client(user, provider) as client:
            created = client.post(
                "/v1/conversations", json={}, headers={"Idempotency-Key": str(uuid.uuid4())}
            )
            conversation_id = created.json()["id"]
            before = metrics_text(client)
            with client.stream(
                "POST",
                f"/v1/conversations/{conversation_id}/responses",
                json={"client_message_id": str(uuid.uuid4()), "content": "hi"},
                headers={"Idempotency-Key": str(uuid.uuid4())},
            ) as response:
                b"".join(response.iter_bytes())
            after = metrics_text(client)

        _assert_moves(
            after,
            before,
            'copilot_http_requests_total{code="",'
            'endpoint="/v1/conversations/{conversation_id}/responses",status="200"}',
        )
        _assert_moves(after, before, 'copilot_events_emitted_total{type="message.delta"}')
        _assert_moves(
            after,
            before,
            'copilot_runs_terminal_total{error_code="",model="grok-4.6",status="completed"}',
        )
        _assert_moves(after, before, "copilot_stream_bytes_total")
        _assert_moves(after, before, 'copilot_provider_first_token_seconds_count{model="grok-4.6"}')
        _assert_moves(after, before, 'copilot_service_first_event_seconds_count{model="grok-4.6"}')
        _assert_moves(after, before, 'copilot_generation_duration_seconds_count{model="grok-4.6"}')
        _assert_moves(after, before, 'copilot_db_tx_seconds_count{op="create_response"}')
        _assert_moves(
            after,
            before,
            "copilot_accept_latency_seconds_count{"
            'endpoint="/v1/conversations/{conversation_id}/responses"}',
        )
        # Gauge: the supervisor only creates the series when it tracks the model.
        assert 'copilot_runs_active{model="grok-4.6"}' in after

    asyncio.run(scenario())


def test_idempotency_replay_and_conflict_are_counted() -> None:
    from app.providers.fake import FakeProvider

    async def scenario() -> None:
        user = new_user("idem-metrics")
        provider = FakeProvider(deltas=["ok"], finish_reason="stop")
        with observable_client(user, provider) as client:
            conversation_id = client.post(
                "/v1/conversations", json={}, headers={"Idempotency-Key": str(uuid.uuid4())}
            ).json()["id"]
            key = str(uuid.uuid4())
            body = {"client_message_id": str(uuid.uuid4()), "content": "hi"}
            before = metrics_text(client)
            for _ in range(2):
                with client.stream(
                    "POST",
                    f"/v1/conversations/{conversation_id}/responses",
                    json=body,
                    headers={"Idempotency-Key": key},
                ) as response:
                    b"".join(response.iter_bytes())
            conflict = client.post(
                f"/v1/conversations/{conversation_id}/responses",
                json={"client_message_id": str(uuid.uuid4()), "content": "different"},
                headers={"Idempotency-Key": key},
            )
            assert conflict.status_code == 409
            after = metrics_text(client)

        assert (
            _delta(
                after,
                before,
                'copilot_idempotency_hits_total{operation="create_response",result="replay"}',
            )
            > 0
        )
        assert (
            _delta(
                after,
                before,
                'copilot_idempotency_hits_total{operation="create_response",result="conflict"}',
            )
            > 0
        )

    asyncio.run(scenario())


def test_reconnect_observes_gap_and_catchup_series() -> None:
    from datetime import UTC, datetime, timedelta

    from tests.support import (
        seed_conversation,
        seed_event,
        seed_messages,
        seed_run,
        session_factory,
    )

    async def scenario() -> None:
        user = new_user("reconnect-metrics")
        with observable_client(user) as client:
            factory = session_factory()
            async with factory() as session:
                async with session.begin():
                    conversation_id = await seed_conversation(session, user)
                    user_message_id, assistant_message_id = await seed_messages(
                        session, conversation_id
                    )
                    run_id = await seed_run(
                        session,
                        conversation_id,
                        user,
                        user_message_id,
                        assistant_message_id,
                        status="completed",
                        last_sequence=3,
                        lease_expires_at=datetime.now(UTC) + timedelta(minutes=10),
                    )
                    # Sequence 1 is missing: the follower is behind the retained window.
                    await seed_event(session, run_id, 2)
                    await seed_event(session, run_id, 3)
            before = metrics_text(client)
            with client.stream(
                "POST",
                f"/v1/response-runs/{run_id}/stream",
                json={"after_sequence": 0},
            ) as response:
                assert response.status_code == 200
                b"".join(response.iter_bytes())
            after = metrics_text(client)

        assert _delta(after, before, "copilot_sequence_gaps_total") > 0
        assert _delta(after, before, "copilot_reconnect_catchup_seconds_count") > 0

    asyncio.run(scenario())


def test_cancel_ack_is_observed_from_request_to_terminal() -> None:
    from datetime import UTC, datetime, timedelta

    from app.chat.event_writer import cancel_run
    from tests.support import (
        seed_conversation,
        seed_messages,
        seed_run,
        session_factory,
        writer_factory,
    )

    async def scenario() -> None:
        user = new_user("cancel-metrics")
        with observable_client(user) as client:
            factory = session_factory()
            async with factory() as session:
                async with session.begin():
                    conversation_id = await seed_conversation(session, user)
                    user_message_id, assistant_message_id = await seed_messages(
                        session, conversation_id
                    )
                    run_id = await seed_run(
                        session,
                        conversation_id,
                        user,
                        user_message_id,
                        assistant_message_id,
                        status="queued",
                        lease_expires_at=datetime.now(UTC) + timedelta(minutes=10),
                    )
            cancel = client.post(f"/v1/response-runs/{run_id}/cancel", json={})
            assert cancel.status_code == 200
            assert cancel.json()["cancel_requested_at"] is not None
            before = metrics_text(client)
            writes = writer_factory()
            async with writes() as session:
                await cancel_run(run_id, session=session)
            after = metrics_text(client)

        assert _delta(after, before, "copilot_cancel_ack_seconds_count") > 0

    asyncio.run(scenario())


def test_orphaned_run_metric_counts_reaped_runs() -> None:
    from datetime import UTC, datetime, timedelta

    from app.chat.responses import reap_expired_leases
    from tests.support import (
        build_settings,
        seed_conversation,
        seed_messages,
        seed_run,
        session_factory,
    )

    async def scenario() -> None:
        user = new_user("orphan-metrics")
        with observable_client(user) as client:
            factory = session_factory()
            async with factory() as session:
                async with session.begin():
                    conversation_id = await seed_conversation(session, user)
                    user_message_id, assistant_message_id = await seed_messages(
                        session, conversation_id
                    )
                    await seed_run(
                        session,
                        conversation_id,
                        user,
                        user_message_id,
                        assistant_message_id,
                        status="queued",
                        lease_expires_at=datetime.now(UTC) - timedelta(minutes=1),
                    )
            before = metrics_text(client)
            async with factory() as session:
                reaped = await reap_expired_leases(session=session, settings=build_settings())
            assert reaped >= 1
            after = metrics_text(client)

        assert _delta(after, before, "copilot_runs_orphaned_total") > 0

    asyncio.run(scenario())


def test_bounded_client_request_id_matches_the_diagnostic_id() -> None:
    with observable_client(new_user("reqid-bound")) as client:
        safe = client.get(
            "/v1/conversations/not-a-uuid", headers={"X-Request-ID": "trace-abc_1.2:3"}
        )
        assert safe.status_code == 400
        assert safe.headers["x-request-id"] == "trace-abc_1.2:3"
        assert safe.json()["diagnostic_id"] == "trace-abc_1.2:3"

        oversized = "z" * 500
        bounded = client.get("/v1/conversations/not-a-uuid", headers={"X-Request-ID": oversized})
        assert bounded.headers["x-request-id"] != oversized
        assert bounded.json()["diagnostic_id"] == bounded.headers["x-request-id"]


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


def test_problem_code_label_is_recorded_on_error_responses() -> None:
    with observable_client(new_user("problem-code")) as client:
        before = metrics_text(client)
        missing = client.get(f"/v1/conversations/{uuid.uuid4()}")
        assert missing.status_code == 404
        after = metrics_text(client)

    _assert_moves(
        after,
        before,
        'copilot_http_requests_total{code="not_found",'
        'endpoint="/v1/conversations/{conversation_id}",status="404"}',
    )


def test_json_formatter_carries_observability_correlation_fields() -> None:
    import json

    from app.observability.logging import JsonFormatter

    record = logging.LogRecord(
        name="copilot.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="accepted",
        args=(),
        exc_info=None,
    )
    record.request_id = "req-1"  # type: ignore[attr-defined]
    record.trace_id = "trace-1"  # type: ignore[attr-defined]
    record.conversation_id = "conv-1"  # type: ignore[attr-defined]
    record.diagnostic_id = "req-1"  # type: ignore[attr-defined]
    record.idempotency_key_hash = "abcd"  # type: ignore[attr-defined]
    record.error_code = "rate_limited"  # type: ignore[attr-defined]
    record.http_status = 429  # type: ignore[attr-defined]
    payload = json.loads(JsonFormatter().format(record))

    # observability.md §2 fields must survive the formatter allowlist.
    assert payload["conversation_id"] == "conv-1"
    assert payload["diagnostic_id"] == "req-1"
    assert payload["idempotency_key_hash"] == "abcd"
    assert payload["error_code"] == "rate_limited"
    assert payload["http_status"] == 429
