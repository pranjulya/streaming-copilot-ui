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
                "uid": new_user("enum"),
                "umid": user_message_id,
                "amid": assistant_message_id,
            },
            "23514",
        )

    asyncio.run(scenario())
