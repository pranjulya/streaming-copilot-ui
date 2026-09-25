import asyncio
import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from tests.support import (
    build_settings,
    database_url,
    new_user,
    seed_conversation,
    seed_event,
    seed_messages,
    seed_run,
    writer_factory,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="Set TEST_DATABASE_URL for real Postgres"
)


async def expect_sqlstate(sql: str, params: dict[str, object], sqlstate: str) -> None:
    engine = create_async_engine(database_url())
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                with pytest.raises(IntegrityError) as caught:
                    await connection.execute(text(sql), params)
                assert caught.value.orig.sqlstate == sqlstate, (
                    f"expected {sqlstate}, got {caught.value.orig.sqlstate}"
                )
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


async def seed_run_in_new_engine(
    status: str = "queued",
) -> tuple[uuid.UUID, str, uuid.UUID, uuid.UUID, uuid.UUID]:
    engine = create_async_engine(database_url())
    user = new_user("run-seed")
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            conversation_id = await seed_conversation(connection, user)
            user_message_id, assistant_message_id = await seed_messages(connection, conversation_id)
            run_id = await seed_run(
                connection, conversation_id, user, user_message_id, assistant_message_id
            )
            await transaction.commit()
    finally:
        await engine.dispose()
    return run_id, user, conversation_id, user_message_id, assistant_message_id


def test_one_active_run_per_conversation_enforced() -> None:
    async def scenario() -> None:
        engine = create_async_engine(database_url())
        user = new_user("one-active")
        try:
            async with engine.connect() as connection:
                transaction = await connection.begin()
                conversation_id = await seed_conversation(connection, user)
                user_message_id, assistant_message_id = await seed_messages(
                    connection, conversation_id
                )
                await seed_run(
                    connection, conversation_id, user, user_message_id, assistant_message_id
                )
                with pytest.raises(IntegrityError) as caught:
                    await seed_run(
                        connection, conversation_id, user, user_message_id, assistant_message_id
                    )
                assert caught.value.orig.sqlstate == "23505"
                await transaction.rollback()
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_stream_events_primary_key_is_run_and_sequence() -> None:
    async def scenario() -> None:
        engine = create_async_engine(database_url())
        user = new_user("pk-event")
        try:
            async with engine.connect() as connection:
                transaction = await connection.begin()
                conversation_id = await seed_conversation(connection, user)
                user_message_id, assistant_message_id = await seed_messages(
                    connection, conversation_id
                )
                run_id = await seed_run(
                    connection, conversation_id, user, user_message_id, assistant_message_id
                )
                await seed_event(connection, run_id, 1)
                with pytest.raises(IntegrityError) as caught:
                    await connection.execute(
                        text(
                            "INSERT INTO stream_events (run_id, sequence, event_id, type,"
                            " payload, occurred_at)"
                            " VALUES (:run_id, 1, :event_id, 'message.delta', '{}'::jsonb, now())"
                        ),
                        {"run_id": run_id, "event_id": uuid.uuid4()},
                    )
                assert caught.value.orig.sqlstate == "23505"
                await transaction.rollback()
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_stream_event_ids_are_globally_unique() -> None:
    async def scenario() -> None:
        engine = create_async_engine(database_url())
        user = new_user("event-id")
        shared_event_id = uuid.uuid4()
        try:
            async with engine.connect() as connection:
                transaction = await connection.begin()
                conversation_id = await seed_conversation(connection, user)
                user_message_id, assistant_message_id = await seed_messages(
                    connection, conversation_id
                )
                run_id = await seed_run(
                    connection, conversation_id, user, user_message_id, assistant_message_id
                )
                await seed_event(connection, run_id, 1, event_id=shared_event_id)
                with pytest.raises(IntegrityError) as caught:
                    await connection.execute(
                        text(
                            "INSERT INTO stream_events (run_id, sequence, event_id, type,"
                            " payload, occurred_at)"
                            " VALUES (:run_id, 2, :event_id, 'message.delta', '{}'::jsonb, now())"
                        ),
                        {"run_id": run_id, "event_id": shared_event_id},
                    )
                assert caught.value.orig.sqlstate == "23505"
                await transaction.rollback()
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_run_owner_must_match_conversation_owner() -> None:
    async def scenario() -> None:
        engine = create_async_engine(database_url())
        user = new_user("owner-mismatch")
        try:
            async with engine.connect() as connection:
                transaction = await connection.begin()
                conversation_id = await seed_conversation(connection, user)
                user_message_id, assistant_message_id = await seed_messages(
                    connection, conversation_id
                )
                await transaction.commit()
        finally:
            await engine.dispose()
        await expect_sqlstate(
            "INSERT INTO response_runs (id, conversation_id, user_id, user_message_id,"
            " assistant_message_id, status, attempt, last_sequence, created_at, updated_at)"
            " VALUES (:id, :cid, 'someone-else', :umid, :amid, 'queued', 1, 0, now(), now())",
            {
                "id": uuid.uuid4(),
                "cid": conversation_id,
                "umid": user_message_id,
                "amid": assistant_message_id,
            },
            "23503",
        )

    asyncio.run(scenario())


def test_run_status_outside_enum_rejected() -> None:
    async def scenario() -> None:
        (
            _,
            user,
            conversation_id,
            user_message_id,
            assistant_message_id,
        ) = await seed_run_in_new_engine()
        await expect_sqlstate(
            "INSERT INTO response_runs (id, conversation_id, user_id, user_message_id,"
            " assistant_message_id, status, attempt, last_sequence, created_at, updated_at)"
            " VALUES (:id, :cid, :uid, :umid, :amid, 'bogus', 1, 0, now(), now())",
            {
                "id": uuid.uuid4(),
                "cid": conversation_id,
                "uid": user,
                "umid": user_message_id,
                "amid": assistant_message_id,
            },
            "23514",
        )

    asyncio.run(scenario())


async def seed_run_and_messages(
    *, status: str = "queued"
) -> tuple[str, uuid.UUID, uuid.UUID, uuid.UUID]:
    from app.persistence.session import create_database_engine, create_session_factory
    from tests.support import seed_conversation, seed_messages, seed_run

    factory = create_session_factory(create_database_engine(database_url()))
    user = new_user("writer")
    async with factory() as session:
        async with session.begin():
            conversation_id = await seed_conversation(session, user)
            user_message_id, assistant_message_id = await seed_messages(session, conversation_id)
            run_id = await seed_run(
                session, conversation_id, user, user_message_id, assistant_message_id, status=status
            )
    return user, run_id, user_message_id, assistant_message_id


def test_illegal_transition_completed_to_streaming_raises() -> None:
    from app.chat.event_writer import start_run
    from app.chat.state_machine import InvalidStateTransition

    async def scenario() -> None:
        _, run_id, *_ = await seed_run_and_messages(status="completed")
        factory = writer_factory()
        async with factory() as session:
            with pytest.raises(InvalidStateTransition):
                await start_run(run_id, session=session)

    asyncio.run(scenario())


def test_start_run_is_sequence_one_and_deltas_follow_without_gaps() -> None:
    from sqlalchemy import text as sql_text

    from app.chat.event_writer import append_delta, start_run

    async def scenario() -> None:
        _, run_id, _, assistant_message_id = await seed_run_and_messages()
        factory = writer_factory()

        async with factory() as session:
            started = await start_run(run_id, session=session)
        assert started.sequence == 1
        assert started.type == "response.started"
        assert started.data["attempt"] == 1
        assert started.data["user_message_id"]
        assert started.data["assistant_message_id"] == str(assistant_message_id)
        assert started.data["client_message_id"]

        async with factory() as session:
            first = await append_delta(run_id, "Hel", session=session)
        async with factory() as session:
            second = await append_delta(run_id, "lo", session=session)
        assert first.sequence == 2
        assert second.sequence == 3
        assert first.data["content_index"] == 0
        assert second.data["content_index"] == 3

        async with factory() as session:
            content = (
                await session.execute(
                    sql_text("SELECT content FROM messages WHERE id = :id"),
                    {"id": assistant_message_id},
                )
            ).scalar_one()
            last_sequence = (
                await session.execute(
                    sql_text("SELECT last_sequence FROM response_runs WHERE id = :id"),
                    {"id": run_id},
                )
            ).scalar_one()
            event_sequences = (
                (
                    await session.execute(
                        sql_text(
                            "SELECT sequence FROM stream_events WHERE run_id = :id"
                            " ORDER BY sequence"
                        ),
                        {"id": run_id},
                    )
                )
                .scalars()
                .all()
            )
        assert content == "Hello"
        assert last_sequence == 3
        assert list(event_sequences) == [1, 2, 3]

    asyncio.run(scenario())


def test_content_index_counts_code_points_for_supplementary_characters() -> None:
    from sqlalchemy import text as sql_text

    from app.chat.event_writer import append_delta, start_run

    async def scenario() -> None:
        _, run_id, _, assistant_message_id = await seed_run_and_messages()
        factory = writer_factory()
        async with factory() as session:
            await start_run(run_id, session=session)
        async with factory() as session:
            thumbs = await append_delta(run_id, "👍", session=session)
        async with factory() as session:
            rest = await append_delta(run_id, "ok", session=session)
        assert thumbs.data["content_index"] == 0
        assert rest.data["content_index"] == 1
        async with factory() as session:
            content = (
                await session.execute(
                    sql_text("SELECT content FROM messages WHERE id = :id"),
                    {"id": assistant_message_id},
                )
            ).scalar_one()
        assert content == "👍ok"
        assert len(content) == 3

    asyncio.run(scenario())


def test_start_run_is_idempotent_when_already_streaming() -> None:
    from sqlalchemy import text as sql_text

    from app.chat.event_writer import start_run

    async def scenario() -> None:
        _, run_id, *_ = await seed_run_and_messages()
        factory = writer_factory()
        async with factory() as session:
            first = await start_run(run_id, session=session)
        async with factory() as session:
            second = await start_run(run_id, session=session)
        assert second.to_dict() == first.to_dict()
        async with factory() as session:
            count = (
                await session.execute(
                    sql_text(
                        "SELECT count(*) FROM stream_events"
                        " WHERE run_id = :id AND type = 'response.started'"
                    ),
                    {"id": run_id},
                )
            ).scalar_one()
        assert count == 1

    asyncio.run(scenario())


def test_append_delta_rejects_cancel_requested_run() -> None:
    from app.api.auth import Actor
    from app.api.errors import AppError
    from app.chat.event_writer import append_delta, start_run
    from app.chat.responses import request_cancel

    async def scenario() -> None:
        user, run_id, *_ = await seed_run_and_messages()
        factory = writer_factory()
        async with factory() as session:
            await start_run(run_id, session=session)
        async with factory() as session:
            await request_cancel(run_id, Actor(user_id=user), session=session)
        with pytest.raises(AppError) as caught:
            async with factory() as session:
                await append_delta(run_id, "more", session=session)
        assert caught.value.code == "invalid_run_state"

    asyncio.run(scenario())


def test_cancel_run_from_cancelling_lands_cancelled() -> None:
    from sqlalchemy import text as sql_text

    from app.chat.event_writer import cancel_run

    async def scenario() -> None:
        _, run_id, _, message_id = await seed_run_and_messages(status="cancelling")
        factory = writer_factory()
        async with factory() as session:
            cancelled = await cancel_run(run_id, session=session)
        assert cancelled.type == "response.cancelled"
        async with factory() as session:
            status = (
                await session.execute(
                    sql_text("SELECT status FROM response_runs WHERE id = :id"),
                    {"id": run_id},
                )
            ).scalar_one()
            message_status = (
                await session.execute(
                    sql_text("SELECT status FROM messages WHERE id = :id"),
                    {"id": message_id},
                )
            ).scalar_one()
            count = (
                await session.execute(
                    sql_text("SELECT count(*) FROM stream_events WHERE run_id = :id"),
                    {"id": run_id},
                )
            ).scalar_one()
        assert status == "cancelled"
        assert message_status == "cancelled"
        assert count == 1

    asyncio.run(scenario())


def test_concurrent_writers_produce_gapless_sequences() -> None:
    from sqlalchemy import text as sql_text

    from app.chat.event_writer import append_delta, start_run

    async def scenario() -> None:
        _, run_id, *_ = await seed_run_and_messages()
        factory = writer_factory()
        async with factory() as session:
            await start_run(run_id, session=session)

        async def write(delta: str):
            async with factory() as session:
                return await append_delta(run_id, delta, session=session)

        first, second = await asyncio.gather(write("A"), write("B"))
        assert sorted([first.sequence, second.sequence]) == [2, 3]
        assert {first.data["delta"], second.data["delta"]} == {"A", "B"}

        async with factory() as session:
            sequences = (
                (
                    await session.execute(
                        sql_text(
                            "SELECT sequence FROM stream_events WHERE run_id = :id"
                            " ORDER BY sequence"
                        ),
                        {"id": run_id},
                    )
                )
                .scalars()
                .all()
            )
        assert list(sequences) == [1, 2, 3]

    asyncio.run(scenario())


def test_append_usage_does_not_change_message_content() -> None:
    from sqlalchemy import text as sql_text

    from app.chat.event_writer import append_delta, append_usage, start_run
    from app.providers.protocol import Usage

    async def scenario() -> None:
        _, run_id, _, assistant_message_id = await seed_run_and_messages()
        factory = writer_factory()
        async with factory() as session:
            await start_run(run_id, session=session)
        async with factory() as session:
            await append_delta(run_id, "partial", session=session)
        async with factory() as session:
            usage_event = await append_usage(
                run_id, Usage(input_tokens=10, output_tokens=5), session=session
            )

        assert usage_event.type == "usage.updated"
        assert usage_event.data == {"input_tokens": 10, "output_tokens": 5}
        async with factory() as session:
            content = (
                await session.execute(
                    sql_text("SELECT content FROM messages WHERE id = :id"),
                    {"id": assistant_message_id},
                )
            ).scalar_one()
            tokens = (
                await session.execute(
                    sql_text("SELECT input_tokens FROM response_runs WHERE id = :id"),
                    {"id": run_id},
                )
            ).scalar_one()
        assert content == "partial"
        assert tokens == 10

    asyncio.run(scenario())


def test_complete_run_is_idempotent_and_content_matches_message() -> None:
    from sqlalchemy import text as sql_text

    from app.chat.event_writer import CompletionResult, append_delta, complete_run, start_run
    from app.providers.protocol import Usage

    async def scenario() -> None:
        _, run_id, _, assistant_message_id = await seed_run_and_messages()
        factory = writer_factory()
        async with factory() as session:
            await start_run(run_id, session=session)
        async with factory() as session:
            await append_delta(run_id, "Hello ", session=session)
        result = CompletionResult(
            content="Hello world",
            finish_reason="stop",
            usage=Usage(input_tokens=7, output_tokens=4),
        )
        async with factory() as session:
            message_event, response_event = await complete_run(run_id, result, session=session)
        assert message_event.type == "message.completed"
        assert response_event.type == "response.completed"
        assert message_event.sequence + 1 == response_event.sequence
        assert message_event.data["content"] == "Hello world"
        assert response_event.data["finish_reason"] == "stop"
        assert response_event.data["usage"] == {"input_tokens": 7, "output_tokens": 4}

        async with factory() as session:
            repeated_message, repeated_response = await complete_run(
                run_id, result, session=session
            )
        assert repeated_message.to_dict() == message_event.to_dict()
        assert repeated_response.to_dict() == response_event.to_dict()

        async with factory() as session:
            canonical = (
                await session.execute(
                    sql_text("SELECT content FROM messages WHERE id = :id"),
                    {"id": assistant_message_id},
                )
            ).scalar_one()
            count = (
                await session.execute(
                    sql_text(
                        "SELECT count(*) FROM stream_events WHERE run_id = :id"
                        " AND type IN ('message.completed', 'response.completed')"
                    ),
                    {"id": run_id},
                )
            ).scalar_one()
        assert canonical == "Hello world"
        assert message_event.data["content"] == canonical
        assert count == 2

    asyncio.run(scenario())


def test_complete_run_emits_zero_usage_when_provider_omits_it() -> None:
    from sqlalchemy import text as sql_text

    from app.chat.event_writer import CompletionResult, complete_run, start_run

    async def scenario() -> None:
        _, run_id, *_ = await seed_run_and_messages()
        factory = writer_factory()
        async with factory() as session:
            await start_run(run_id, session=session)
        async with factory() as session:
            _, response_event = await complete_run(
                run_id, CompletionResult(content="done", finish_reason="stop"), session=session
            )
        assert response_event.data["usage"] == {"input_tokens": 0, "output_tokens": 0}
        async with factory() as session:
            tokens = (
                await session.execute(
                    sql_text(
                        "SELECT input_tokens, output_tokens FROM response_runs WHERE id = :id"
                    ),
                    {"id": run_id},
                )
            ).one()
        assert tuple(tokens) == (0, 0)

    asyncio.run(scenario())


def test_cancel_from_queued_and_streaming_lands_cancelled_with_partial() -> None:
    from sqlalchemy import text as sql_text

    from app.chat.event_writer import append_delta, cancel_run, start_run

    async def scenario() -> None:
        _, queued_run, _, queued_message = await seed_run_and_messages()
        factory = writer_factory()
        async with factory() as session:
            cancelled = await cancel_run(queued_run, session=session)
        assert cancelled.type == "response.cancelled"
        assert cancelled.data["reason"] == "user_requested"
        async with factory() as session:
            status = (
                await session.execute(
                    sql_text("SELECT status FROM response_runs WHERE id = :id"),
                    {"id": queued_run},
                )
            ).scalar_one()
            message_status = (
                await session.execute(
                    sql_text("SELECT status FROM messages WHERE id = :id"),
                    {"id": queued_message},
                )
            ).scalar_one()
        assert status == "cancelled"
        assert message_status == "cancelled"

        _, streaming_run, _, streaming_message = await seed_run_and_messages()
        async with factory() as session:
            await start_run(streaming_run, session=session)
        async with factory() as session:
            await append_delta(streaming_run, "partial answer", session=session)
        async with factory() as session:
            cancelled = await cancel_run(streaming_run, session=session)
        async with factory() as session:
            again = await cancel_run(streaming_run, session=session)
        assert again.to_dict() == cancelled.to_dict()
        assert cancelled.data["content"] == "partial answer"
        assert cancelled.data["partial_content_retained"] is True

        async with factory() as session:
            rows = (
                (
                    await session.execute(
                        sql_text(
                            "SELECT type FROM stream_events WHERE run_id = :id ORDER BY sequence"
                        ),
                        {"id": streaming_run},
                    )
                )
                .scalars()
                .all()
            )
            content = (
                await session.execute(
                    sql_text("SELECT content FROM messages WHERE id = :id"),
                    {"id": streaming_message},
                )
            ).scalar_one()
        assert "message.completed" not in rows
        assert content == "partial answer"

    asyncio.run(scenario())


def test_fail_run_is_terminal_and_idempotent() -> None:
    from sqlalchemy import text as sql_text

    from app.chat.event_writer import SafeFailure, append_delta, fail_run, start_run
    from app.chat.state_machine import InvalidStateTransition

    async def scenario() -> None:
        _, run_id, _, assistant_message = await seed_run_and_messages()
        factory = writer_factory()
        async with factory() as session:
            await start_run(run_id, session=session)
        async with factory() as session:
            await append_delta(run_id, "half", session=session)
        failure = SafeFailure(code="provider_unavailable", message="temporarily unavailable")
        async with factory() as session:
            failed = await fail_run(run_id, failure, session=session)
        async with factory() as session:
            again = await fail_run(run_id, failure, session=session)
        assert failed.type == "response.failed"
        assert again.to_dict() == failed.to_dict()
        assert failed.data["content"] == "half"
        assert failed.data["retryable"] is True
        assert failed.data["diagnostic_id"]

        async with factory() as session:
            with pytest.raises(InvalidStateTransition):
                await start_run(run_id, session=session)
            status, error_code, content, message_status = (
                await session.execute(
                    sql_text(
                        "SELECT status, error_code, (SELECT content FROM messages WHERE id = :mid),"
                        " (SELECT status FROM messages WHERE id = :mid)"
                        " FROM response_runs WHERE id = :rid"
                    ),
                    {"mid": assistant_message, "rid": run_id},
                )
            ).one()
        assert status == "failed"
        assert error_code == "provider_unavailable"
        assert content == "half"
        assert message_status == "failed"

    asyncio.run(scenario())


async def seed_reap_target(
    factory,
    user: str,
    *,
    owner: uuid.UUID | None,
    lease,
) -> uuid.UUID:
    from tests.support import seed_conversation, seed_messages, seed_run

    async with factory() as session:
        async with session.begin():
            conversation_id = await seed_conversation(session, user)
            user_message_id, assistant_message_id = await seed_messages(session, conversation_id)
            return await seed_run(
                session,
                conversation_id,
                user,
                user_message_id,
                assistant_message_id,
                owner_instance_id=owner,
                lease_expires_at=lease,
            )


async def reap_statuses(factory, run_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    from sqlalchemy import text as sql_text

    async with factory() as session:
        rows = (
            await session.execute(
                sql_text("SELECT id, status FROM response_runs WHERE id = ANY(:ids)"),
                {"ids": [str(identifier) for identifier in run_ids]},
            )
        ).all()
    return {row[0]: row[1] for row in rows}


def test_reaper_rechecks_the_lease_under_the_lock() -> None:
    from datetime import timedelta

    from sqlalchemy import text as sql_text

    from app.chat.responses import _fail_targets
    from app.settings import Settings

    async def scenario() -> None:
        _, run_id, *_ = await seed_run_and_messages()
        factory = writer_factory()
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    sql_text(
                        "UPDATE response_runs SET owner_instance_id = :owner,"
                        " lease_expires_at = :lease WHERE id = :id"
                    ),
                    {
                        "owner": uuid.uuid4(),
                        "lease": datetime.now(UTC) + timedelta(seconds=60),
                        "id": run_id,
                    },
                )
        async with factory() as session:
            reaped = await _fail_targets(
                session, [run_id], Settings(_env_file=None), include_own_instance=False
            )
        assert reaped == 0
        async with factory() as session:
            status = (
                await session.execute(
                    sql_text("SELECT status FROM response_runs WHERE id = :id"),
                    {"id": run_id},
                )
            ).scalar_one()
        assert status == "queued"

    asyncio.run(scenario())


def test_completing_a_terminal_run_in_another_state_is_invalid_run_state() -> None:
    from app.api.errors import AppError
    from app.chat.event_writer import CompletionResult, complete_run

    async def scenario() -> None:
        _, run_id, *_ = await seed_run_and_messages(status="failed")
        factory = writer_factory()
        result = CompletionResult(content="late", finish_reason="stop")
        with pytest.raises(AppError) as caught:
            async with factory() as session:
                await complete_run(run_id, result, session=session)
        assert caught.value.status_code == 409
        assert caught.value.code == "invalid_run_state"

    asyncio.run(scenario())


def test_startup_reaper_fails_null_expired_and_own_instance_runs() -> None:
    from datetime import timedelta

    from sqlalchemy import text as sql_text

    from app.chat.responses import reap_orphaned_runs

    async def scenario() -> None:
        factory = writer_factory()
        settings = build_settings()
        now = datetime.now(UTC)
        expired_other = await seed_reap_target(
            factory, new_user("reap1"), owner=uuid.uuid4(), lease=now - timedelta(minutes=1)
        )
        null_lease = await seed_reap_target(
            factory, new_user("reap2"), owner=uuid.uuid4(), lease=None
        )
        own_live = await seed_reap_target(
            factory,
            new_user("reap3"),
            owner=settings.instance_id,
            lease=now + timedelta(minutes=10),
        )
        other_live = await seed_reap_target(
            factory, new_user("reap4"), owner=uuid.uuid4(), lease=now + timedelta(minutes=10)
        )

        async with factory() as session:
            await reap_orphaned_runs(session=session, settings=settings)

        statuses = await reap_statuses(factory, [expired_other, null_lease, own_live, other_live])
        assert statuses[expired_other] == "failed"
        assert statuses[null_lease] == "failed"
        assert statuses[own_live] == "failed"
        assert statuses[other_live] == "queued"

        async with factory() as session:
            error_code = (
                await session.execute(
                    sql_text("SELECT error_code FROM response_runs WHERE id = :id"),
                    {"id": expired_other},
                )
            ).scalar_one()
            events = (
                (
                    await session.execute(
                        sql_text(
                            "SELECT type FROM stream_events WHERE run_id = :id ORDER BY sequence"
                        ),
                        {"id": expired_other},
                    )
                )
                .scalars()
                .all()
            )
        assert error_code == "server_restart"
        assert list(events) == ["response.failed"]

    asyncio.run(scenario())


def test_periodic_reaper_only_touches_null_or_expired_leases() -> None:
    from datetime import timedelta

    from app.chat.responses import reap_expired_leases

    async def scenario() -> None:
        factory = writer_factory()
        settings = build_settings()
        now = datetime.now(UTC)
        this_live = await seed_reap_target(
            factory, new_user("per1"), owner=settings.instance_id, lease=now + timedelta(minutes=10)
        )
        this_expired = await seed_reap_target(
            factory, new_user("per2"), owner=settings.instance_id, lease=now - timedelta(seconds=1)
        )
        other_expired = await seed_reap_target(
            factory, new_user("per3"), owner=uuid.uuid4(), lease=now - timedelta(minutes=5)
        )
        other_null = await seed_reap_target(
            factory, new_user("per4"), owner=uuid.uuid4(), lease=None
        )
        other_live = await seed_reap_target(
            factory, new_user("per5"), owner=uuid.uuid4(), lease=now + timedelta(minutes=10)
        )

        async with factory() as session:
            await reap_expired_leases(session=session, settings=settings)

        statuses = await reap_statuses(
            factory, [this_live, this_expired, other_expired, other_null, other_live]
        )
        assert statuses[this_live] == "queued"
        assert statuses[this_expired] == "failed"
        assert statuses[other_expired] == "failed"
        assert statuses[other_null] == "failed"
        assert statuses[other_live] == "queued"

    asyncio.run(scenario())


def test_new_instance_id_waits_for_expiry_then_any_replica_fails_the_run() -> None:
    from datetime import timedelta

    from sqlalchemy import text as sql_text

    from app.chat.responses import reap_expired_leases

    async def scenario() -> None:
        factory = writer_factory()
        old_settings = build_settings()
        run_id = await seed_reap_target(
            factory,
            new_user("restart-new"),
            owner=uuid.uuid4(),
            lease=datetime.now(UTC) + timedelta(minutes=10),
        )

        async with factory() as session:
            await reap_expired_leases(session=session, settings=old_settings)

        assert (await reap_statuses(factory, [run_id]))[run_id] == "queued"

        async with factory() as session:
            async with session.begin():
                await session.execute(
                    sql_text(
                        "UPDATE response_runs SET lease_expires_at = now() - interval '1 s'"
                        " WHERE id = :id"
                    ),
                    {"id": run_id},
                )
        any_replica = build_settings()
        async with factory() as session:
            await reap_expired_leases(session=session, settings=any_replica)

        assert (await reap_statuses(factory, [run_id]))[run_id] == "failed"

    asyncio.run(scenario())


def test_same_instance_id_startup_reaper_fails_but_periodic_does_not() -> None:
    from datetime import timedelta

    from app.chat.responses import reap_expired_leases, reap_orphaned_runs

    async def scenario() -> None:
        factory = writer_factory()
        settings = build_settings()
        run_id = await seed_reap_target(
            factory,
            new_user("restart-same"),
            owner=settings.instance_id,
            lease=datetime.now(UTC) + timedelta(minutes=10),
        )

        async with factory() as session:
            await reap_expired_leases(session=session, settings=settings)

        assert (await reap_statuses(factory, [run_id]))[run_id] == "queued"

        async with factory() as session:
            await reap_orphaned_runs(session=session, settings=settings)

        assert (await reap_statuses(factory, [run_id]))[run_id] == "failed"

    asyncio.run(scenario())
