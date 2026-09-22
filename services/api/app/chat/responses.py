from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import Actor
from app.api.errors import AppError
from app.persistence.models import (
    Conversation,
    IdempotencyRecord,
    Message,
    ResponseRun,
)
from app.settings import Settings

ACTIVE_RUN_STATUSES = ("queued", "streaming", "cancelling")
TERMINAL_RUN_STATUSES = ("completed", "cancelled", "failed")
PROVIDER_NAME = "xai"
DEFAULT_TITLE = "New conversation"


@dataclass(frozen=True)
class CreateResponse:
    conversation_id: UUID
    client_message_id: UUID
    content: str
    idempotency_key: UUID
    request_hash: str


async def _lock_user(session: AsyncSession, user_id: str) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:user_id))"), {"user_id": user_id}
    )


async def _owned_conversation(
    session: AsyncSession, conversation_id: UUID, user_id: str
) -> Conversation:
    conversation = await session.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id
        )
    )
    if conversation is None:
        raise AppError(404, "not_found", "Conversation not found")
    return conversation


async def _active_run_id(session: AsyncSession, conversation_id: UUID) -> UUID | None:
    result = await session.scalars(
        select(ResponseRun.id).where(
            ResponseRun.conversation_id == conversation_id,
            ResponseRun.status.in_(ACTIVE_RUN_STATUSES),
        )
    )
    return result.first()


async def _assert_capacity(session: AsyncSession, user_id: str, settings: Settings) -> None:
    active = await session.scalar(
        select(func.count(ResponseRun.id)).where(
            ResponseRun.user_id == user_id,
            ResponseRun.status.in_(ACTIVE_RUN_STATUSES),
        )
    )
    if (active or 0) >= settings.max_active_runs_per_user:
        raise AppError(
            409,
            "too_many_active_runs",
            "Too many active responses for this user",
        )


async def _find_key(
    session: AsyncSession,
    user_id: str,
    operation: str,
    key: UUID,
    request_hash: str,
) -> IdempotencyRecord | None:
    record = await session.get(IdempotencyRecord, (user_id, operation, key))
    if record is None:
        return None
    if record.expires_at <= datetime.now(UTC):
        await session.delete(record)
        return None
    if record.request_hash != request_hash:
        raise AppError(
            409,
            "idempotency_key_conflict",
            "Idempotency-Key was already used with a different request",
        )
    return record


async def _keyed_run(
    session: AsyncSession,
    record: IdempotencyRecord | None,
    user_id: str,
) -> ResponseRun | None:
    if record is None:
        return None
    run = await session.get(ResponseRun, record.resource_id)
    if run is None or run.user_id != user_id:
        raise AppError(
            409,
            "idempotency_key_conflict",
            "Idempotency-Key refers to a run that no longer exists",
        )
    return run


def _store_key(
    session: AsyncSession,
    *,
    user_id: str,
    operation: str,
    key: UUID,
    request_hash: str,
    resource_id: UUID,
    settings: Settings,
) -> None:
    session.add(
        IdempotencyRecord(
            user_id=user_id,
            operation=operation,
            key=key,
            request_hash=request_hash,
            resource_id=resource_id,
            expires_at=datetime.now(UTC) + timedelta(hours=settings.idempotency_ttl_hours),
        )
    )


async def _insert_run(session: AsyncSession, run: ResponseRun) -> None:
    session.add(run)


def _queued_run(
    *,
    conversation_id: UUID,
    user_id: str,
    user_message_id: UUID,
    assistant_message_id: UUID,
    attempt: int,
    settings: Settings,
) -> ResponseRun:
    now = datetime.now(UTC)
    return ResponseRun(
        conversation_id=conversation_id,
        user_id=user_id,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
        status="queued",
        attempt=attempt,
        provider=PROVIDER_NAME,
        model=settings.xai_model,
        last_sequence=0,
        owner_instance_id=settings.instance_id,
        lease_expires_at=now + timedelta(seconds=settings.lease_seconds),
        created_at=now,
        updated_at=now,
    )


async def create_response(
    cmd: CreateResponse, actor: Actor, *, session: AsyncSession, settings: Settings
) -> ResponseRun:
    content = cmd.content.strip()
    if not content:
        raise AppError(400, "validation_failed", "content must not be empty")
    if len(content) > settings.max_message_chars:
        raise AppError(400, "validation_failed", "content exceeds the configured limit")
    operation = "create_response"
    for _ in range(2):
        try:
            async with session.begin():
                await _lock_user(session, actor.user_id)
                conversation = await _owned_conversation(
                    session, cmd.conversation_id, actor.user_id
                )
                if conversation.archived_at is not None:
                    raise AppError(409, "conversation_archived", "Conversation is archived")
                record = await _find_key(
                    session, actor.user_id, operation, cmd.idempotency_key, cmd.request_hash
                )
                replay = await _keyed_run(session, record, actor.user_id)
                if replay is not None:
                    return replay
                active = await _active_run_id(session, cmd.conversation_id)
                if active is not None:
                    raise AppError(
                        409,
                        "conversation_busy",
                        "Conversation already has an active response",
                        conversation_id=str(cmd.conversation_id),
                        active_run_id=str(active),
                    )
                await _assert_capacity(session, actor.user_id, settings)
                existing_message = await session.scalar(
                    select(Message).where(
                        Message.conversation_id == cmd.conversation_id,
                        Message.client_message_id == cmd.client_message_id,
                    )
                )
                if existing_message is not None:
                    existing_run = await session.scalar(
                        select(ResponseRun).where(
                            ResponseRun.user_message_id == existing_message.id
                        )
                    )
                    if existing_run is None:
                        raise AppError(
                            409,
                            "idempotency_key_conflict",
                            "Existing turn has no response run",
                        )
                    return existing_run
                user_message = Message(
                    conversation_id=cmd.conversation_id,
                    role="user",
                    content=content,
                    status="complete",
                    client_message_id=cmd.client_message_id,
                )
                session.add(user_message)
                await session.flush()
                assistant_message = Message(
                    conversation_id=cmd.conversation_id,
                    role="assistant",
                    content="",
                    status="partial",
                    in_reply_to_id=user_message.id,
                )
                session.add(assistant_message)
                await session.flush()
                run = _queued_run(
                    conversation_id=cmd.conversation_id,
                    user_id=actor.user_id,
                    user_message_id=user_message.id,
                    assistant_message_id=assistant_message.id,
                    attempt=1,
                    settings=settings,
                )
                await _insert_run(session, run)
                await session.flush()
                _store_key(
                    session,
                    user_id=actor.user_id,
                    operation=operation,
                    key=cmd.idempotency_key,
                    request_hash=cmd.request_hash,
                    resource_id=run.id,
                    settings=settings,
                )
                first_turn = (
                    await session.scalar(
                        select(func.count(Message.id)).where(
                            Message.conversation_id == cmd.conversation_id,
                            Message.role == "user",
                        )
                    )
                    == 1
                )
                if first_turn and conversation.title == DEFAULT_TITLE:
                    conversation.title = content[:80]
                    conversation.updated_at = datetime.now(UTC)
                return run
        except IntegrityError:
            continue
    raise AppError(
        409,
        "conversation_busy",
        "Conversation already has an active response",
        conversation_id=str(cmd.conversation_id),
    )


async def retry_run(
    source_run_id: UUID,
    actor: Actor,
    *,
    session: AsyncSession,
    settings: Settings,
    idempotency_key: UUID | None = None,
    request_hash: str | None = None,
) -> ResponseRun:
    operation = "retry_run"
    for _ in range(2):
        try:
            async with session.begin():
                await _lock_user(session, actor.user_id)
                source = await session.scalar(
                    select(ResponseRun).where(
                        ResponseRun.id == source_run_id,
                        ResponseRun.user_id == actor.user_id,
                    )
                )
                if source is None:
                    raise AppError(404, "not_found", "Response run not found")
                if source.status not in ("failed", "cancelled"):
                    raise AppError(
                        409,
                        "invalid_run_state",
                        "Retry is only allowed from failed or cancelled runs",
                    )
                conversation = await _owned_conversation(
                    session, source.conversation_id, actor.user_id
                )
                if conversation.archived_at is not None:
                    raise AppError(409, "conversation_archived", "Conversation is archived")
                if idempotency_key is not None and request_hash is not None:
                    record = await _find_key(
                        session, actor.user_id, operation, idempotency_key, request_hash
                    )
                    replay = await _keyed_run(session, record, actor.user_id)
                    if replay is not None:
                        return replay
                active = await _active_run_id(session, source.conversation_id)
                if active is not None:
                    raise AppError(
                        409,
                        "conversation_busy",
                        "Conversation already has an active response",
                        conversation_id=str(source.conversation_id),
                        active_run_id=str(active),
                    )
                await _assert_capacity(session, actor.user_id, settings)
                previous = await session.scalar(
                    select(Message).where(
                        Message.in_reply_to_id == source.user_message_id,
                        Message.role == "assistant",
                        Message.is_visible.is_(True),
                    )
                )
                if previous is not None:
                    previous.is_visible = False
                    previous.updated_at = datetime.now(UTC)
                new_assistant = Message(
                    conversation_id=source.conversation_id,
                    role="assistant",
                    content="",
                    status="partial",
                    in_reply_to_id=source.user_message_id,
                    version=(previous.version + 1) if previous is not None else 1,
                )
                session.add(new_assistant)
                await session.flush()
                run = _queued_run(
                    conversation_id=source.conversation_id,
                    user_id=actor.user_id,
                    user_message_id=source.user_message_id,
                    assistant_message_id=new_assistant.id,
                    attempt=source.attempt + 1,
                    settings=settings,
                )
                await _insert_run(session, run)
                await session.flush()
                if idempotency_key is not None and request_hash is not None:
                    _store_key(
                        session,
                        user_id=actor.user_id,
                        operation=operation,
                        key=idempotency_key,
                        request_hash=request_hash,
                        resource_id=run.id,
                        settings=settings,
                    )
                return run
        except IntegrityError:
            continue
    raise AppError(
        409,
        "conversation_busy",
        "Conversation already has an active response",
    )


async def regenerate_message(
    user_message_id: UUID,
    actor: Actor,
    *,
    session: AsyncSession,
    settings: Settings,
    idempotency_key: UUID | None = None,
    request_hash: str | None = None,
) -> ResponseRun:
    operation = "regenerate_message"
    for _ in range(2):
        try:
            async with session.begin():
                await _lock_user(session, actor.user_id)
                message = await session.scalar(
                    select(Message)
                    .join(Conversation, Message.conversation_id == Conversation.id)
                    .where(
                        Message.id == user_message_id,
                        Message.role == "user",
                        Conversation.user_id == actor.user_id,
                    )
                )
                if message is None:
                    raise AppError(404, "not_found", "Message not found")
                conversation = await _owned_conversation(
                    session, message.conversation_id, actor.user_id
                )
                if conversation.archived_at is not None:
                    raise AppError(409, "conversation_archived", "Conversation is archived")
                active = await _active_run_id(session, message.conversation_id)
                if active is not None:
                    raise AppError(
                        409,
                        "conversation_busy",
                        "Conversation already has an active response",
                        conversation_id=str(message.conversation_id),
                        active_run_id=str(active),
                    )
                visible = await session.scalar(
                    select(Message).where(
                        Message.in_reply_to_id == user_message_id,
                        Message.role == "assistant",
                        Message.is_visible.is_(True),
                    )
                )
                if visible is None:
                    raise AppError(
                        409,
                        "invalid_run_state",
                        "There is no visible answer to regenerate",
                    )
                if idempotency_key is not None and request_hash is not None:
                    record = await _find_key(
                        session, actor.user_id, operation, idempotency_key, request_hash
                    )
                    replay = await _keyed_run(session, record, actor.user_id)
                    if replay is not None:
                        return replay
                await _assert_capacity(session, actor.user_id, settings)
                source_run = await session.scalar(
                    select(ResponseRun)
                    .where(ResponseRun.assistant_message_id == visible.id)
                    .order_by(ResponseRun.created_at.desc())
                    .limit(1)
                )
                if source_run is not None and source_run.status == "completed":
                    attempt = 1
                elif source_run is not None:
                    attempt = source_run.attempt + 1
                else:
                    attempt = 1
                visible.is_visible = False
                visible.updated_at = datetime.now(UTC)
                new_assistant = Message(
                    conversation_id=message.conversation_id,
                    role="assistant",
                    content="",
                    status="partial",
                    in_reply_to_id=user_message_id,
                    version=visible.version + 1,
                )
                session.add(new_assistant)
                await session.flush()
                run = _queued_run(
                    conversation_id=message.conversation_id,
                    user_id=actor.user_id,
                    user_message_id=user_message_id,
                    assistant_message_id=new_assistant.id,
                    attempt=attempt,
                    settings=settings,
                )
                await _insert_run(session, run)
                await session.flush()
                if idempotency_key is not None and request_hash is not None:
                    _store_key(
                        session,
                        user_id=actor.user_id,
                        operation=operation,
                        key=idempotency_key,
                        request_hash=request_hash,
                        resource_id=run.id,
                        settings=settings,
                    )
                return run
        except IntegrityError:
            continue
    raise AppError(
        409,
        "conversation_busy",
        "Conversation already has an active response",
    )
