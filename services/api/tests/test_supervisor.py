import asyncio
import os
import uuid

import pytest

from tests.support import database_url, new_user, seed_conversation, session_factory

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="Set TEST_DATABASE_URL for real Postgres"
)


def context_settings(**overrides: object):
    from app.settings import Settings

    return Settings(_env_file=None, database_url=database_url(), **overrides)  # type: ignore[arg-type]


_ORDER = __import__("itertools").count()


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
        settings = context_settings(context_char_budget=40, system_prompt="SYS")
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
        assert result.dropped_turns == 2

    asyncio.run(scenario())


def test_context_includes_only_visible_nonempty_assistant_messages() -> None:
    from app.chat.context import build_context

    async def scenario() -> None:
        factory = session_factory()
        user = new_user("ctx-vis")
        settings = context_settings(context_char_budget=10000, system_prompt="SYS")
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
        settings = context_settings(context_char_budget=30, system_prompt="SYS")
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
