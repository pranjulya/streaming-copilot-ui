import asyncio
import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from tests.support import (
    database_url,
    new_user,
    seed_conversation,
    seed_event,
    seed_messages,
    seed_run,
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
        run_id, *_ = await seed_run_in_new_engine()
        engine = create_async_engine(database_url())
        try:
            async with engine.begin() as connection:
                await seed_event(connection, run_id, 1)
        finally:
            await engine.dispose()
        await expect_sqlstate(
            "INSERT INTO stream_events (run_id, sequence, event_id, type, payload, occurred_at)"
            " VALUES (:run_id, 1, :event_id, 'message.delta', '{}'::jsonb, now())",
            {"run_id": run_id, "event_id": uuid.uuid4()},
            "23505",
        )

    asyncio.run(scenario())


def test_stream_event_ids_are_globally_unique() -> None:
    async def scenario() -> None:
        run_id, *_ = await seed_run_in_new_engine()
        shared_event_id = uuid.uuid4()
        engine = create_async_engine(database_url())
        try:
            async with engine.begin() as connection:
                await seed_event(connection, run_id, 1, event_id=shared_event_id)
        finally:
            await engine.dispose()
        await expect_sqlstate(
            "INSERT INTO stream_events (run_id, sequence, event_id, type, payload, occurred_at)"
            " VALUES (:run_id, 2, :event_id, 'message.delta', '{}'::jsonb, now())",
            {"run_id": run_id, "event_id": shared_event_id},
            "23505",
        )

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


def writer_session_factory():
    from app.persistence.session import create_database_engine, create_session_factory

    return create_session_factory(create_database_engine(database_url()))


def test_illegal_transition_completed_to_streaming_raises() -> None:
    from app.chat.event_writer import start_run
    from app.chat.state_machine import InvalidStateTransition

    async def scenario() -> None:
        _, run_id, *_ = await seed_run_and_messages(status="completed")
        factory = writer_session_factory()
        async with factory() as session:
            with pytest.raises(InvalidStateTransition):
                await start_run(run_id, session=session)

    asyncio.run(scenario())


def test_start_run_is_sequence_one_and_deltas_follow_without_gaps() -> None:
    from sqlalchemy import text as sql_text

    from app.chat.event_writer import append_delta, start_run

    async def scenario() -> None:
        _, run_id, _, assistant_message_id = await seed_run_and_messages()
        factory = writer_session_factory()

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


def test_concurrent_writers_produce_gapless_sequences() -> None:
    from sqlalchemy import text as sql_text

    from app.chat.event_writer import append_delta, start_run

    async def scenario() -> None:
        _, run_id, *_ = await seed_run_and_messages()
        factory = writer_session_factory()
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

    from app.chat.event_writer import Usage, append_delta, append_usage, start_run

    async def scenario() -> None:
        _, run_id, _, assistant_message_id = await seed_run_and_messages()
        factory = writer_session_factory()
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

    from app.chat.event_writer import CompletionResult, Usage, append_delta, complete_run, start_run

    async def scenario() -> None:
        _, run_id, _, assistant_message_id = await seed_run_and_messages()
        factory = writer_session_factory()
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
        assert message_event.sequence == message_event.sequence
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


def test_cancel_from_queued_and_streaming_lands_cancelled_with_partial() -> None:
    from sqlalchemy import text as sql_text

    from app.chat.event_writer import append_delta, cancel_run, start_run

    async def scenario() -> None:
        _, queued_run, _, queued_message = await seed_run_and_messages()
        factory = writer_session_factory()
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
        factory = writer_session_factory()
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
