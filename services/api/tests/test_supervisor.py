import asyncio
import itertools
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from tests.support import (
    build_settings,
    new_user,
    seed_conversation,
    session_factory,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="Set TEST_DATABASE_URL for real Postgres"
)


_ORDER = itertools.count()


async def seed_message(
    session,
    conversation_id: uuid.UUID,
    *,
    role: str,
    content: str,
    status: str,
    is_visible: bool = True,
    in_reply_to_id: uuid.UUID | None = None,
    version: int = 1,
) -> uuid.UUID:
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import text

    message_id = uuid.uuid4()
    created_at = datetime.now(UTC) + timedelta(seconds=next(_ORDER))
    params: dict[str, object] = {
        "id": message_id,
        "cid": conversation_id,
        "role": role,
        "content": content,
        "status": status,
        "visible": is_visible,
        "version": version,
        "rid": in_reply_to_id,
        "cmid": uuid.uuid4() if role == "user" else None,
        "created_at": created_at,
    }
    await session.execute(
        text(
            "INSERT INTO messages (id, conversation_id, role, content, status,"
            " client_message_id, in_reply_to_id, version, is_visible, created_at, updated_at)"
            " VALUES (:id, :cid, :role, :content, :status, :cmid, :rid, :version, :visible,"
            " :created_at, :created_at)"
        ),
        params,
    )
    return message_id


def test_context_keeps_newest_turns_within_budget_and_drops_oldest() -> None:
    from app.chat.context import build_context

    async def scenario() -> None:
        factory = session_factory()
        user = new_user("ctx")
        settings = build_settings(context_char_budget=40, system_prompt="SYS")
        async with factory() as session:
            async with session.begin():
                conversation_id = await seed_conversation(session, user)
                user_a = await seed_message(
                    session, conversation_id, role="user", content="a" * 20, status="complete"
                )
                await seed_message(
                    session,
                    conversation_id,
                    role="assistant",
                    content="b" * 20,
                    status="complete",
                    in_reply_to_id=user_a,
                )
                user_c = await seed_message(
                    session, conversation_id, role="user", content="c" * 20, status="complete"
                )
                await seed_message(
                    session,
                    conversation_id,
                    role="assistant",
                    content="d" * 20,
                    status="complete",
                    in_reply_to_id=user_c,
                )
        async with factory() as session:
            result = await build_context(session, conversation_id, settings=settings)
        assert result.messages[0].role == "system"
        assert result.messages[0].content == "SYS"
        contents = [message.content for message in result.messages[1:]]
        assert contents == ["c" * 20, "d" * 20]
        assert result.dropped_turns == 1

    asyncio.run(scenario())


def test_context_drops_whole_turns_instead_of_orphan_assistants() -> None:
    from app.chat.context import build_context

    async def scenario() -> None:
        factory = session_factory()
        user = new_user("ctx-turn")
        settings = build_settings(context_char_budget=12, system_prompt="SYS")
        async with factory() as session:
            async with session.begin():
                conversation_id = await seed_conversation(session, user)
                user_a = await seed_message(
                    session, conversation_id, role="user", content="aa", status="complete"
                )
                await seed_message(
                    session,
                    conversation_id,
                    role="assistant",
                    content="bbbbbbbb",
                    status="complete",
                    in_reply_to_id=user_a,
                )
                user_c = await seed_message(
                    session, conversation_id, role="user", content="cc", status="complete"
                )
                await seed_message(
                    session,
                    conversation_id,
                    role="assistant",
                    content="dd",
                    status="complete",
                    in_reply_to_id=user_c,
                )
        async with factory() as session:
            result = await build_context(session, conversation_id, settings=settings)
        contents = [message.content for message in result.messages[1:]]
        roles = [message.role for message in result.messages[1:]]
        assert contents == ["cc", "dd"]
        assert roles == ["user", "assistant"]
        assert result.dropped_turns == 1

    asyncio.run(scenario())


def test_context_includes_only_visible_nonempty_assistant_messages() -> None:
    from app.chat.context import build_context

    async def scenario() -> None:
        factory = session_factory()
        user = new_user("ctx-vis")
        settings = build_settings(context_char_budget=10000, system_prompt="SYS")
        async with factory() as session:
            async with session.begin():
                conversation_id = await seed_conversation(session, user)
                first = await seed_message(
                    session, conversation_id, role="user", content="q1", status="complete"
                )
                await seed_message(
                    session,
                    conversation_id,
                    role="assistant",
                    content="hidden old version",
                    status="complete",
                    is_visible=False,
                    in_reply_to_id=first,
                )
                await seed_message(
                    session,
                    conversation_id,
                    role="assistant",
                    content="visible answer",
                    status="complete",
                    in_reply_to_id=first,
                    version=2,
                )
                second = await seed_message(
                    session, conversation_id, role="user", content="q2", status="complete"
                )
                await seed_message(
                    session,
                    conversation_id,
                    role="assistant",
                    content="",
                    status="failed",
                    in_reply_to_id=second,
                )
                third = await seed_message(
                    session, conversation_id, role="user", content="q3", status="complete"
                )
                await seed_message(
                    session,
                    conversation_id,
                    role="assistant",
                    content="cancelled partial",
                    status="cancelled",
                    in_reply_to_id=third,
                )
        async with factory() as session:
            result = await build_context(session, conversation_id, settings=settings)
        contents = [message.content for message in result.messages]
        assert contents == ["SYS", "q1", "visible answer", "q2", "q3", "cancelled partial"]
        roles = [message.role for message in result.messages]
        assert roles == ["system", "user", "assistant", "user", "user", "assistant"]

    asyncio.run(scenario())


def test_context_reports_dropped_count_without_content_in_logs(caplog) -> None:
    import logging

    from app.chat.context import build_context

    async def scenario() -> None:
        factory = session_factory()
        user = new_user("ctx-log")
        secret = "SECRET-CONTENT-MARKER"
        settings = build_settings(context_char_budget=30, system_prompt="SYS")
        async with factory() as session:
            async with session.begin():
                conversation_id = await seed_conversation(session, user)
                await seed_message(
                    session, conversation_id, role="user", content=secret, status="complete"
                )
                await seed_message(
                    session,
                    conversation_id,
                    role="user",
                    content="newest message",
                    status="complete",
                )
        with caplog.at_level(logging.INFO):
            async with factory() as session:
                await build_context(session, conversation_id, settings=settings)
        assert "dropped" in caplog.text.lower()
        assert secret not in caplog.text

    asyncio.run(scenario())


def supervisor_settings(**overrides: object):
    values: dict[str, object] = {
        "lease_seconds": 5,
        "lease_renew_seconds": 1,
        "provider_idle_timeout_seconds": 2,
        "generation_timeout_seconds": 30,
        "delta_flush_ms": 10,
        "delta_flush_chars": 1000,
        "max_output_chars": 100000,
    }
    values.update(overrides)
    return build_settings(**values)


async def seed_supervised_run(user: str, *, instance_id, status: str = "queued"):
    from datetime import UTC, datetime, timedelta

    from tests.support import seed_messages, seed_run

    factory = session_factory()
    async with factory() as session:
        async with session.begin():
            conversation_id = await seed_conversation(session, user)
            user_message_id, assistant_message_id = await seed_messages(session, conversation_id)
            run_id = await seed_run(
                session,
                conversation_id,
                user,
                user_message_id,
                assistant_message_id,
                status=status,
                owner_instance_id=instance_id,
                lease_expires_at=datetime.now(UTC) + timedelta(seconds=1),
            )
    return run_id, conversation_id, assistant_message_id


async def run_state(run_id: uuid.UUID) -> tuple[str, str | None]:
    from sqlalchemy import text

    factory = session_factory()
    async with factory() as session:
        row = (
            await session.execute(
                text("SELECT status, error_code FROM response_runs WHERE id = :id"),
                {"id": run_id},
            )
        ).one()
    return row[0], row[1]


async def wait_terminal(run_id: uuid.UUID, *, wait_seconds: float = 10.0) -> str:
    deadline = asyncio.get_running_loop().time() + wait_seconds
    while asyncio.get_running_loop().time() < deadline:
        status, _ = await run_state(run_id)
        if status in ("completed", "cancelled", "failed"):
            return status
        await asyncio.sleep(0.02)
    raise AssertionError(f"run {run_id} did not reach a terminal state")


async def event_types(run_id: uuid.UUID) -> list[str]:
    from sqlalchemy import text

    factory = session_factory()
    async with factory() as session:
        rows = (
            await session.execute(
                text("SELECT type FROM stream_events WHERE run_id = :id ORDER BY sequence"),
                {"id": run_id},
            )
        ).scalars()
    return list(rows)


async def assistant_content(assistant_message_id: uuid.UUID) -> tuple[str, str]:
    from sqlalchemy import text

    factory = session_factory()
    async with factory() as session:
        row = (
            await session.execute(
                text("SELECT content, status FROM messages WHERE id = :id"),
                {"id": assistant_message_id},
            )
        ).one()
    return row[0], row[1]


def make_supervisor(provider, settings):
    from app.chat.supervisor import GenerationSupervisor
    from tests.support import writer_factory

    return GenerationSupervisor(
        session_factory=writer_factory(), provider=provider, settings=settings
    )


def test_supervisor_start_renews_existing_lease_and_refuses_null_lease() -> None:
    from sqlalchemy import text

    from app.providers.fake import FakeProvider

    async def scenario() -> None:
        settings = supervisor_settings(lease_seconds=60)
        run_id, _, _ = await seed_supervised_run(
            new_user("sup-lease"), instance_id=settings.instance_id
        )
        supervisor = make_supervisor(FakeProvider(deltas=["slow"], delay_seconds=5), settings)
        try:
            await supervisor.start(run_id)
            factory = session_factory()
            async with factory() as session:
                lease = (
                    await session.execute(
                        text("SELECT lease_expires_at FROM response_runs WHERE id = :id"),
                        {"id": run_id},
                    )
                ).scalar_one()
            assert lease > datetime.now(UTC) + timedelta(seconds=30)

            null_run, _, _ = await seed_supervised_run(new_user("sup-null"), instance_id=None)
            async with factory() as session:
                await session.execute(
                    text(
                        "UPDATE response_runs SET owner_instance_id = NULL,"
                        " lease_expires_at = NULL WHERE id = :id"
                    ),
                    {"id": null_run},
                )
            with pytest.raises(RuntimeError):
                await supervisor.start(null_run)
            status, _ = await run_state(null_run)
            assert status == "queued"
        finally:
            await supervisor.shutdown(0.05)

    asyncio.run(scenario())


def test_supervisor_completes_run_and_persists_events() -> None:
    from app.providers.fake import FakeProvider
    from app.providers.protocol import Usage

    async def scenario() -> None:
        settings = supervisor_settings()
        run_id, _, assistant_id = await seed_supervised_run(
            new_user("sup-complete"), instance_id=settings.instance_id
        )
        supervisor = make_supervisor(
            FakeProvider(deltas=["Back", "pressure"], finish_reason="stop", usage=Usage(3, 2)),
            settings,
        )
        try:
            await supervisor.start(run_id)
            assert await wait_terminal(run_id) == "completed"
        finally:
            await supervisor.shutdown(0.05)
        content, message_status = await assistant_content(assistant_id)
        assert content == "Backpressure"
        assert message_status == "complete"
        types = await event_types(run_id)
        assert types[0] == "response.started"
        assert types[-2:] == ["message.completed", "response.completed"]
        assert "message.delta" in types

    asyncio.run(scenario())


def test_supervisor_fails_run_on_provider_error_keeping_partial() -> None:
    from app.providers.fake import FakeProvider
    from app.providers.protocol import ProviderError

    async def scenario() -> None:
        settings = supervisor_settings()
        run_id, _, assistant_id = await seed_supervised_run(
            new_user("sup-fail"), instance_id=settings.instance_id
        )
        supervisor = make_supervisor(
            FakeProvider(
                deltas=["partial-answer"],
                fail_after=1,
                failure=ProviderError(code="provider_unavailable", message="down"),
            ),
            settings,
        )
        try:
            await supervisor.start(run_id)
            assert await wait_terminal(run_id) == "failed"
        finally:
            await supervisor.shutdown(0.05)
        status, error_code = await run_state(run_id)
        assert status == "failed"
        assert error_code == "provider_unavailable"
        content, message_status = await assistant_content(assistant_id)
        assert content == "partial-answer"
        assert message_status == "failed"
        assert await event_types(run_id) == ["response.started", "message.delta", "response.failed"]

    asyncio.run(scenario())


def test_supervisor_enforces_output_limit() -> None:
    from app.providers.fake import FakeProvider

    async def scenario() -> None:
        settings = supervisor_settings(max_output_chars=12, delta_flush_chars=5)
        run_id, _, _ = await seed_supervised_run(
            new_user("sup-limit"), instance_id=settings.instance_id
        )
        supervisor = make_supervisor(FakeProvider(deltas=["12345", "67890", "abcde"]), settings)
        try:
            await supervisor.start(run_id)
            assert await wait_terminal(run_id) == "failed"
        finally:
            await supervisor.shutdown(0.05)
        _, error_code = await run_state(run_id)
        assert error_code == "output_limit_exceeded"

    asyncio.run(scenario())


def test_supervisor_enforces_idle_timeout_on_hanging_provider() -> None:
    from app.providers.fake import FakeProvider

    async def scenario() -> None:
        settings = supervisor_settings(provider_idle_timeout_seconds=1)
        run_id, _, _ = await seed_supervised_run(
            new_user("sup-hang"), instance_id=settings.instance_id
        )
        supervisor = make_supervisor(FakeProvider(deltas=["x"], hang_after=0), settings)
        try:
            await supervisor.start(run_id)
            assert await wait_terminal(run_id) == "failed"
        finally:
            await supervisor.shutdown(0.05)
        _, error_code = await run_state(run_id)
        assert error_code == "provider_timeout"

    asyncio.run(scenario())


def test_supervisor_observes_cancel_request_and_commits_cancelled() -> None:
    from sqlalchemy import text

    from app.providers.fake import FakeProvider

    async def scenario() -> None:
        settings = supervisor_settings()
        run_id, _, assistant_id = await seed_supervised_run(
            new_user("sup-cancel"), instance_id=settings.instance_id
        )
        supervisor = make_supervisor(
            FakeProvider(deltas=["x"] * 5000, delay_seconds=0.01), settings
        )
        factory = session_factory()
        try:
            await supervisor.start(run_id)
            deadline = asyncio.get_running_loop().time() + 5
            while asyncio.get_running_loop().time() < deadline:
                if "message.delta" in await event_types(run_id):
                    break
                await asyncio.sleep(0.02)
            async with factory() as session:
                async with session.begin():
                    await session.execute(
                        text("UPDATE response_runs SET cancel_requested_at = now() WHERE id = :id"),
                        {"id": run_id},
                    )
            assert await wait_terminal(run_id) == "cancelled"
        finally:
            await supervisor.shutdown(0.05)
        content, message_status = await assistant_content(assistant_id)
        assert content
        assert message_status == "cancelled"
        types = await event_types(run_id)
        assert types[-1] == "response.cancelled"
        assert "message.completed" not in types

    asyncio.run(scenario())


def test_supervisor_shutdown_fails_remaining_owned_runs() -> None:
    from app.providers.fake import FakeProvider

    async def scenario() -> None:
        settings = supervisor_settings()
        run_id, _, _ = await seed_supervised_run(
            new_user("sup-shutdown"), instance_id=settings.instance_id
        )
        supervisor = make_supervisor(
            FakeProvider(deltas=["x"] * 5000, delay_seconds=0.01), settings
        )
        await supervisor.start(run_id)
        deadline = asyncio.get_running_loop().time() + 5
        while asyncio.get_running_loop().time() < deadline:
            if "response.started" in await event_types(run_id):
                break
            await asyncio.sleep(0.02)
        await supervisor.shutdown(0.1)
        status, error_code = await run_state(run_id)
        assert status == "failed"
        assert error_code == "server_restart"
        assert (await event_types(run_id))[-1] == "response.failed"

    asyncio.run(scenario())


def test_wait_budget_honors_delta_flush_ms() -> None:
    from app.chat.supervisor import wait_budget_seconds

    wait = wait_budget_seconds(
        now=1.0,
        last_activity=1.0,
        renew_at=10.0,
        buffered_since=1.0,
        has_buffer=True,
        idle_timeout=30.0,
        flush_ms=40,
    )
    assert wait == pytest.approx(0.04)


def test_supervisor_completes_when_provider_hangs_after_finish() -> None:
    from app.providers.protocol import CancelSignal, ProviderDelta, ProviderMessage, Usage

    class HangAfterFinish:
        async def stream(self, messages: list[ProviderMessage], *, signal: CancelSignal):
            del messages, signal
            yield ProviderDelta(text="hi")
            yield ProviderDelta(finish_reason="stop", usage=Usage(1, 1))
            await asyncio.Event().wait()
            yield ProviderDelta(text="never")

    async def scenario() -> None:
        settings = supervisor_settings(provider_idle_timeout_seconds=5)
        run_id, _, _ = await seed_supervised_run(
            new_user("sup-hang-finish"), instance_id=settings.instance_id
        )
        supervisor = make_supervisor(HangAfterFinish(), settings)
        try:
            await supervisor.start(run_id)
            assert await wait_terminal(run_id, wait_seconds=2) == "completed"
        finally:
            await supervisor.shutdown(0.05)

    asyncio.run(scenario())


def test_supervisor_cancels_queued_run_before_opening_provider() -> None:
    from sqlalchemy import text

    from app.providers.protocol import CancelSignal, ProviderDelta, ProviderMessage

    opened = {"count": 0}

    class RecordingProvider:
        async def stream(self, messages: list[ProviderMessage], *, signal: CancelSignal):
            del messages, signal
            opened["count"] += 1
            yield ProviderDelta(text="should-not-run")

    async def scenario() -> None:
        settings = supervisor_settings()
        run_id, _, _ = await seed_supervised_run(
            new_user("sup-pre-cancel"), instance_id=settings.instance_id
        )
        factory = session_factory()
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    text("UPDATE response_runs SET cancel_requested_at = now() WHERE id = :id"),
                    {"id": run_id},
                )
        supervisor = make_supervisor(RecordingProvider(), settings)
        try:
            await supervisor.start(run_id)
            assert await wait_terminal(run_id) == "cancelled"
        finally:
            await supervisor.shutdown(0.05)
        assert opened["count"] == 0
        assert "response.started" not in await event_types(run_id)

    asyncio.run(scenario())


def test_supervisor_maps_persistence_errors_to_persistence_failed() -> None:
    from app.api.errors import AppError
    from app.providers.fake import FakeProvider

    async def scenario() -> None:
        settings = supervisor_settings()
        run_id, _, _ = await seed_supervised_run(
            new_user("sup-persist"), instance_id=settings.instance_id
        )
        supervisor = make_supervisor(FakeProvider(deltas=["x"]), settings)

        async def boom(*args: object, **kwargs: object) -> object:
            raise AppError(409, "invalid_run_state", "writer failed")

        supervisor._flush = boom  # type: ignore[method-assign]
        try:
            await supervisor.start(run_id)
            assert await wait_terminal(run_id) == "failed"
        finally:
            await supervisor.shutdown(0.05)
        _, error_code = await run_state(run_id)
        assert error_code == "persistence_failed"

    asyncio.run(scenario())


def test_supervisor_start_fails_queued_run_when_shutting_down() -> None:
    from app.providers.fake import FakeProvider

    async def scenario() -> None:
        settings = supervisor_settings()
        run_id, _, _ = await seed_supervised_run(
            new_user("sup-admit"), instance_id=settings.instance_id
        )
        supervisor = make_supervisor(FakeProvider(deltas=["x"]), settings)
        supervisor._admitting = False
        with pytest.raises(RuntimeError, match="shutting down"):
            await supervisor.start(run_id)
        status, error_code = await run_state(run_id)
        assert status == "failed"
        assert error_code == "server_restart"

    asyncio.run(scenario())


def test_supervisor_shutdown_fails_owned_runs_never_started() -> None:
    from app.providers.fake import FakeProvider

    async def scenario() -> None:
        settings = supervisor_settings()
        run_id, _, _ = await seed_supervised_run(
            new_user("sup-queued-shutdown"), instance_id=settings.instance_id
        )
        supervisor = make_supervisor(FakeProvider(deltas=["x"]), settings)
        await supervisor.shutdown(0.05)
        status, error_code = await run_state(run_id)
        assert status == "failed"
        assert error_code == "server_restart"

    asyncio.run(scenario())


def test_cancel_run_closes_the_supervisor_session() -> None:
    from contextlib import asynccontextmanager

    from sqlalchemy import text

    from app.providers.fake import FakeProvider

    async def scenario() -> None:
        settings = supervisor_settings()
        run_id, _, _ = await seed_supervised_run(
            new_user("sup-session"), instance_id=settings.instance_id
        )
        supervisor = make_supervisor(
            FakeProvider(deltas=["x"] * 5000, delay_seconds=0.01), settings
        )
        real_factory = supervisor._session_factory
        opened = 0
        closed = 0

        @asynccontextmanager
        async def tracking_factory() -> object:
            nonlocal opened, closed
            opened += 1
            async with real_factory() as session:
                try:
                    yield session
                finally:
                    closed += 1

        supervisor._session_factory = tracking_factory  # type: ignore[assignment]
        factory = session_factory()
        try:
            await supervisor.start(run_id)
            deadline = asyncio.get_running_loop().time() + 5
            while asyncio.get_running_loop().time() < deadline:
                if "message.delta" in await event_types(run_id):
                    break
                await asyncio.sleep(0.02)
            async with factory() as session:
                async with session.begin():
                    await session.execute(
                        text("UPDATE response_runs SET cancel_requested_at = now() WHERE id = :id"),
                        {"id": run_id},
                    )
            assert await wait_terminal(run_id) == "cancelled"
        finally:
            await supervisor.shutdown(0.05)
        assert opened == closed
        assert opened > 0

    asyncio.run(scenario())
