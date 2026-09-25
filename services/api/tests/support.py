import json
import os
import uuid
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TERMINAL_STATUSES = ("completed", "cancelled", "failed")


def database_url() -> str:
    return os.environ["TEST_DATABASE_URL"]


def session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(database_url())
    return async_sessionmaker(engine, expire_on_commit=False)


def writer_factory():
    from app.persistence.session import create_database_engine, create_session_factory

    return create_session_factory(create_database_engine(database_url()))


def build_settings(**overrides: object):
    from app.settings import Settings

    return Settings(_env_file=None, database_url=database_url(), **overrides)  # type: ignore[arg-type]


def new_user(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


async def seed_conversation(
    session: AsyncSession, user_id: str, *, title: str = "seed"
) -> uuid.UUID:
    conversation_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO conversations (id, user_id, title, created_at, updated_at)"
            " VALUES (:id, :user_id, :title, :now, :now)"
        ),
        {"id": conversation_id, "user_id": user_id, "title": title, "now": datetime.now(UTC)},
    )
    return conversation_id


async def seed_messages(
    session: AsyncSession, conversation_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID]:
    user_message_id = uuid.uuid4()
    assistant_message_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO messages (id, conversation_id, role, content, status, client_message_id)"
            " VALUES (:id, :cid, 'user', 'hello', 'complete', :cmid)"
        ),
        {"id": user_message_id, "cid": conversation_id, "cmid": uuid.uuid4()},
    )
    await session.execute(
        text(
            "INSERT INTO messages (id, conversation_id, role, content, status, in_reply_to_id)"
            " VALUES (:id, :cid, 'assistant', '', 'partial', :rid)"
        ),
        {"id": assistant_message_id, "cid": conversation_id, "rid": user_message_id},
    )
    return user_message_id, assistant_message_id


async def seed_run(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    user_id: str,
    user_message_id: uuid.UUID,
    assistant_message_id: uuid.UUID,
    *,
    status: str = "queued",
    attempt: int = 1,
    owner_instance_id: uuid.UUID | None = None,
    lease_expires_at: datetime | None = None,
    last_sequence: int = 0,
) -> uuid.UUID:
    run_id = uuid.uuid4()
    now = datetime.now(UTC)
    await session.execute(
        text(
            "INSERT INTO response_runs (id, conversation_id, user_id, user_message_id,"
            " assistant_message_id, status, attempt, provider, model, last_sequence,"
            " owner_instance_id, lease_expires_at, created_at, updated_at)"
            " VALUES (:id, :cid, :uid, :umid, :amid, :status, :attempt, 'fake', 'fake-model',"
            " :last_sequence, :owner, :lease, :now, :now)"
        ),
        {
            "id": run_id,
            "cid": conversation_id,
            "uid": user_id,
            "umid": user_message_id,
            "amid": assistant_message_id,
            "status": status,
            "attempt": attempt,
            "last_sequence": last_sequence,
            "owner": owner_instance_id,
            "lease": lease_expires_at,
            "now": now,
        },
    )
    return run_id


async def seed_event(
    session: AsyncSession,
    run_id: uuid.UUID,
    sequence: int,
    *,
    event_id: uuid.UUID | None = None,
    event_type: str = "message.delta",
    payload: dict[str, object] | None = None,
) -> uuid.UUID:
    identifier = event_id if event_id is not None else uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO stream_events (run_id, sequence, event_id, type, payload, occurred_at)"
            " VALUES (:run_id, :sequence, :event_id, :type, CAST(:payload AS jsonb), :now)"
        ),
        {
            "run_id": run_id,
            "sequence": sequence,
            "event_id": identifier,
            "type": event_type,
            "payload": json.dumps(payload if payload is not None else {}),
            "now": datetime.now(UTC),
        },
    )
    return identifier
