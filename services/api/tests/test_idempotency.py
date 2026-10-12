"""The idempotency-lookup rule, pinned in one place.

Until now the rule was implemented twice — once for conversations and once for
runs — and the two copies had drifted, with neither expiry path covered by a
test. These tests describe the single rule both callers now share.
"""

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.chat.idempotency import find_record, run_still_active
from tests.support import (
    new_user,
    seed_conversation,
    seed_messages,
    seed_run,
    session_factory,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="Set TEST_DATABASE_URL for real Postgres"
)

EXPIRED = datetime.now(UTC) - timedelta(hours=1)
LIVE = datetime.now(UTC) + timedelta(hours=1)


async def _seed_record(
    session: AsyncSession,
    *,
    user_id: str,
    operation: str,
    key: uuid.UUID,
    resource_id: uuid.UUID,
    expires_at: datetime,
) -> None:
    await session.execute(
        text(
            "INSERT INTO idempotency_records"
            " (user_id, operation, key, request_hash, resource_id, expires_at)"
            " VALUES (:user_id, :operation, :key, :request_hash, :resource_id, :expires_at)"
        ),
        {
            "user_id": user_id,
            "operation": operation,
            "key": key,
            "request_hash": "hash-1",
            "resource_id": resource_id,
            "expires_at": expires_at,
        },
    )
    await session.commit()


async def _record_count(session: AsyncSession, user_id: str) -> int:
    count = await session.scalar(
        text("SELECT count(*) FROM idempotency_records WHERE user_id = :user_id"),
        {"user_id": user_id},
    )
    return int(count or 0)


def test_expired_record_is_dropped_so_its_key_becomes_reusable() -> None:
    async def scenario() -> None:
        user_id = new_user("idem")
        async with session_factory()() as session:
            conversation_id = await seed_conversation(session, user_id)
            await session.commit()
            key = uuid.uuid4()
            await _seed_record(
                session,
                user_id=user_id,
                operation="create_conversation",
                key=key,
                resource_id=conversation_id,
                expires_at=EXPIRED,
            )

            found = await find_record(
                session,
                user_id=user_id,
                operation="create_conversation",
                key=key,
                request_hash="hash-1",
            )

            assert found is None
            assert await _record_count(session, user_id) == 0

    asyncio.run(scenario())


def test_expired_record_is_honoured_while_its_run_is_active() -> None:
    async def scenario() -> None:
        user_id = new_user("idem")
        async with session_factory()() as session:
            conversation_id = await seed_conversation(session, user_id)
            user_message_id, assistant_message_id = await seed_messages(session, conversation_id)
            run_id = await seed_run(
                session,
                conversation_id,
                user_id,
                user_message_id,
                assistant_message_id,
                status="queued",
            )
            await session.commit()
            key = uuid.uuid4()
            await _seed_record(
                session,
                user_id=user_id,
                operation="create_response",
                key=key,
                resource_id=run_id,
                expires_at=EXPIRED,
            )

            found = await find_record(
                session,
                user_id=user_id,
                operation="create_response",
                key=key,
                request_hash="hash-1",
                still_live=run_still_active,
            )

            assert found is not None
            assert found.resource_id == run_id

    asyncio.run(scenario())


def test_expired_record_is_dropped_once_its_run_is_terminal() -> None:
    async def scenario() -> None:
        user_id = new_user("idem")
        async with session_factory()() as session:
            conversation_id = await seed_conversation(session, user_id)
            user_message_id, assistant_message_id = await seed_messages(session, conversation_id)
            run_id = await seed_run(
                session,
                conversation_id,
                user_id,
                user_message_id,
                assistant_message_id,
                status="completed",
            )
            await session.commit()
            key = uuid.uuid4()
            await _seed_record(
                session,
                user_id=user_id,
                operation="create_response",
                key=key,
                resource_id=run_id,
                expires_at=EXPIRED,
            )

            found = await find_record(
                session,
                user_id=user_id,
                operation="create_response",
                key=key,
                request_hash="hash-1",
                still_live=run_still_active,
            )

            assert found is None
            assert await _record_count(session, user_id) == 0

    asyncio.run(scenario())


def test_live_record_with_a_different_body_is_a_conflict() -> None:
    async def scenario() -> None:
        user_id = new_user("idem")
        async with session_factory()() as session:
            conversation_id = await seed_conversation(session, user_id)
            await session.commit()
            key = uuid.uuid4()
            await _seed_record(
                session,
                user_id=user_id,
                operation="create_conversation",
                key=key,
                resource_id=conversation_id,
                expires_at=LIVE,
            )

            with pytest.raises(AppError) as raised:
                await find_record(
                    session,
                    user_id=user_id,
                    operation="create_conversation",
                    key=key,
                    request_hash="a-different-body",
                )

            assert raised.value.status_code == 409
            assert raised.value.code == "idempotency_key_conflict"
            assert await _record_count(session, user_id) == 1

    asyncio.run(scenario())
