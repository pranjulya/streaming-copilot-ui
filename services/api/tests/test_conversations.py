import asyncio
import os
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="Set TEST_DATABASE_URL for real Postgres"
)


def database_url() -> str:
    return os.environ["TEST_DATABASE_URL"]


async def with_rollback(run: Callable[[AsyncConnection], Awaitable[None]]) -> None:
    engine = create_async_engine(database_url())
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await run(connection)
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


async def expect_constraint(sql: str, params: dict[str, object], sqlstate: str) -> None:
    from sqlalchemy.exc import IntegrityError

    engine = create_async_engine(database_url())
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                with pytest.raises(IntegrityError) as caught:
                    await connection.execute(text(sql), params)
                assert caught.value.orig.sqlstate == sqlstate, (
                    f"expected SQLSTATE {sqlstate}, got {caught.value.orig.sqlstate}"
                )
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


async def new_conversation() -> uuid.UUID:
    conversation_id = uuid.uuid4()
    engine = create_async_engine(database_url())
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO conversations (id, user_id, title, created_at, updated_at)"
                    " VALUES (:id, :user_id, 'title', :now, :now)"
                ),
                {
                    "id": conversation_id,
                    "user_id": f"owner-{conversation_id}",
                    "now": datetime.now(UTC),
                },
            )
    finally:
        await engine.dispose()
    return conversation_id


def test_conversation_queries_are_scoped_to_the_owner() -> None:
    alice_id = uuid.uuid4()
    bob_id = uuid.uuid4()

    async def scenario(connection: AsyncConnection) -> None:
        await connection.execute(
            text("INSERT INTO conversations (id, user_id, title) VALUES (:id, :user_id, 'a')"),
            {"id": alice_id, "user_id": "alice-owner"},
        )
        await connection.execute(
            text("INSERT INTO conversations (id, user_id, title) VALUES (:id, :user_id, 'b')"),
            {"id": bob_id, "user_id": "bob-owner"},
        )
        rows = (
            await connection.execute(
                text("SELECT id FROM conversations WHERE user_id = 'alice-owner'")
            )
        ).all()
        assert [row[0] for row in rows] == [alice_id]

    asyncio.run(with_rollback(scenario))


def test_valid_user_and_assistant_messages_insert() -> None:
    async def scenario() -> None:
        conversation_id = await new_conversation()
        user_message_id = uuid.uuid4()
        engine = create_async_engine(database_url())
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO messages (id, conversation_id, role, content, status,"
                        " client_message_id) VALUES (:id, :cid, 'user', 'hi', 'complete', :cmid)"
                    ),
                    {"id": user_message_id, "cid": conversation_id, "cmid": uuid.uuid4()},
                )
                await connection.execute(
                    text(
                        "INSERT INTO messages (id, conversation_id, role, content, status,"
                        " in_reply_to_id) VALUES (:id, :cid, 'assistant', 'yo', 'complete', :rid)"
                    ),
                    {"id": uuid.uuid4(), "cid": conversation_id, "rid": user_message_id},
                )
        finally:
            await engine.dispose()

    asyncio.run(scenario())


def test_role_outside_enum_rejected() -> None:
    async def scenario() -> None:
        conversation_id = await new_conversation()
        await expect_constraint(
            "INSERT INTO messages (id, conversation_id, role, content, status, client_message_id)"
            " VALUES (:id, :cid, 'system', 'hi', 'complete', :cmid)",
            {"id": uuid.uuid4(), "cid": conversation_id, "cmid": uuid.uuid4()},
            "23514",
        )

    asyncio.run(scenario())


def test_user_message_requires_client_message_id() -> None:
    async def scenario() -> None:
        conversation_id = await new_conversation()
        await expect_constraint(
            "INSERT INTO messages (id, conversation_id, role, content, status)"
            " VALUES (:id, :cid, 'user', 'hi', 'complete')",
            {"id": uuid.uuid4(), "cid": conversation_id},
            "23514",
        )

    asyncio.run(scenario())


def test_user_message_requires_complete_status() -> None:
    async def scenario() -> None:
        conversation_id = await new_conversation()
        await expect_constraint(
            "INSERT INTO messages (id, conversation_id, role, content, status,"
            " client_message_id) VALUES (:id, :cid, 'user', 'hi', 'partial', :cmid)",
            {"id": uuid.uuid4(), "cid": conversation_id, "cmid": uuid.uuid4()},
            "23514",
        )

    asyncio.run(scenario())


def test_status_outside_enum_rejected() -> None:
    async def scenario() -> None:
        conversation_id = await new_conversation()
        await expect_constraint(
            "INSERT INTO messages (id, conversation_id, role, content, status, client_message_id)"
            " VALUES (:id, :cid, 'user', 'hi', 'pending', :cmid)",
            {"id": uuid.uuid4(), "cid": conversation_id, "cmid": uuid.uuid4()},
            "23514",
        )

    asyncio.run(scenario())


def test_assistant_message_requires_in_reply_to() -> None:
    async def scenario() -> None:
        conversation_id = await new_conversation()
        await expect_constraint(
            "INSERT INTO messages (id, conversation_id, role, content, status)"
            " VALUES (:id, :cid, 'assistant', 'yo', 'partial')",
            {"id": uuid.uuid4(), "cid": conversation_id},
            "23514",
        )

    asyncio.run(scenario())


def test_duplicate_client_message_id_rejected_within_conversation() -> None:
    async def scenario() -> None:
        conversation_id = await new_conversation()
        client_message_id = uuid.uuid4()
        engine = create_async_engine(database_url())
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO messages (id, conversation_id, role, content, status,"
                        " client_message_id) VALUES (:id, :cid, 'user', 'hi', 'complete', :cmid)"
                    ),
                    {"id": uuid.uuid4(), "cid": conversation_id, "cmid": client_message_id},
                )
        finally:
            await engine.dispose()
        await expect_constraint(
            "INSERT INTO messages (id, conversation_id, role, content, status, client_message_id)"
            " VALUES (:id, :cid, 'user', 'hi again', 'complete', :cmid)",
            {"id": uuid.uuid4(), "cid": conversation_id, "cmid": client_message_id},
            "23505",
        )

    asyncio.run(scenario())


def test_only_one_visible_assistant_per_reply() -> None:
    async def scenario() -> None:
        conversation_id = await new_conversation()
        user_message_id = uuid.uuid4()
        engine = create_async_engine(database_url())
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO messages (id, conversation_id, role, content, status,"
                        " client_message_id) VALUES (:id, :cid, 'user', 'hi', 'complete', :cmid)"
                    ),
                    {"id": user_message_id, "cid": conversation_id, "cmid": uuid.uuid4()},
                )
                await connection.execute(
                    text(
                        "INSERT INTO messages (id, conversation_id, role, content, status,"
                        " in_reply_to_id) VALUES (:id, :cid, 'assistant', 'first', 'complete',"
                        " :rid)"
                    ),
                    {"id": uuid.uuid4(), "cid": conversation_id, "rid": user_message_id},
                )
        finally:
            await engine.dispose()
        await expect_constraint(
            "INSERT INTO messages (id, conversation_id, role, content, status, in_reply_to_id)"
            " VALUES (:id, :cid, 'assistant', 'second visible', 'complete', :rid)",
            {"id": uuid.uuid4(), "cid": conversation_id, "rid": user_message_id},
            "23505",
        )

    asyncio.run(scenario())


def test_hidden_assistant_version_allowed_for_same_reply() -> None:
    async def scenario() -> None:
        conversation_id = await new_conversation()
        user_message_id = uuid.uuid4()
        engine = create_async_engine(database_url())
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO messages (id, conversation_id, role, content, status,"
                        " client_message_id) VALUES (:id, :cid, 'user', 'hi', 'complete', :cmid)"
                    ),
                    {"id": user_message_id, "cid": conversation_id, "cmid": uuid.uuid4()},
                )
                await connection.execute(
                    text(
                        "INSERT INTO messages (id, conversation_id, role, content, status,"
                        " in_reply_to_id) VALUES (:id, :cid, 'assistant', 'v1', 'complete', :rid)"
                    ),
                    {"id": uuid.uuid4(), "cid": conversation_id, "rid": user_message_id},
                )
                await connection.execute(
                    text(
                        "INSERT INTO messages (id, conversation_id, role, content, status,"
                        " in_reply_to_id, version, is_visible)"
                        " VALUES (:id, :cid, 'assistant', 'v2 hidden', 'complete', :rid, 2, FALSE)"
                    ),
                    {"id": uuid.uuid4(), "cid": conversation_id, "rid": user_message_id},
                )
        finally:
            await engine.dispose()

    asyncio.run(scenario())
