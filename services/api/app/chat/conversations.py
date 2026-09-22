import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import Actor
from app.api.errors import AppError
from app.persistence import conversations as repository
from app.persistence.models import Conversation, IdempotencyRecord, Message
from app.settings import Settings

DEFAULT_CONVERSATION_TITLE = "New conversation"


@dataclass(frozen=True)
class CreateConversation:
    title: str | None
    idempotency_key: UUID
    request_hash: str


@dataclass(frozen=True)
class ConversationPatch:
    title: str | None = None
    archived: bool | None = None


@dataclass(frozen=True)
class Page[ItemT]:
    items: list[ItemT]
    next_cursor: str | None


@dataclass(frozen=True)
class ConversationSnapshot:
    conversation: Conversation
    messages: list[Message]
    next_cursor: str | None


def _encode_cursor(timestamp: datetime, row_id: UUID) -> str:
    payload = json.dumps({"t": timestamp.isoformat(), "id": str(row_id)}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, UUID] | None:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.b64decode(padded, altchars=b"-_", validate=True))
        timestamp = datetime.fromisoformat(payload["t"])
        row_id = UUID(payload["id"])
    except (ValueError, KeyError, TypeError):
        return None
    if timestamp.tzinfo is None:
        return None
    return timestamp, row_id


def _cursor_or_reject(cursor: str | None) -> tuple[datetime, UUID] | None:
    if cursor is None:
        return None
    decoded = _decode_cursor(cursor)
    if decoded is None:
        raise AppError(400, "validation_failed", "Cursor is not a valid pagination token")
    return decoded


def _expires_at() -> datetime:
    return datetime.now(UTC) + timedelta(hours=Settings().idempotency_ttl_hours)


async def _find_valid_record(
    session: AsyncSession,
    user_id: str,
    operation: str,
    key: UUID,
    request_hash: str,
) -> IdempotencyRecord | None:
    record = await repository.get_idempotency(session, user_id, operation, key)
    if record is None:
        return None
    if record.expires_at <= datetime.now(UTC):
        await repository.delete_idempotency(session, record)
        await session.commit()
        return None
    if record.request_hash != request_hash:
        raise AppError(
            409,
            "idempotency_key_conflict",
            "Idempotency-Key was already used with a different request",
        )
    return record


async def create_conversation(
    cmd: CreateConversation, actor: Actor, *, session: AsyncSession
) -> Conversation:
    operation = "create_conversation"
    for _ in range(2):
        record = await _find_valid_record(
            session, actor.user_id, operation, cmd.idempotency_key, cmd.request_hash
        )
        if record is not None:
            conversation = await repository.get_conversation(
                session, record.resource_id, actor.user_id
            )
            if conversation is None:
                raise AppError(
                    409,
                    "idempotency_key_conflict",
                    "Idempotency-Key refers to a conversation that no longer exists",
                )
            return conversation
        conversation = Conversation(
            user_id=actor.user_id,
            title=cmd.title if cmd.title is not None else DEFAULT_CONVERSATION_TITLE,
        )
        session.add(conversation)
        await session.flush()
        session.add(
            IdempotencyRecord(
                user_id=actor.user_id,
                operation=operation,
                key=cmd.idempotency_key,
                request_hash=cmd.request_hash,
                resource_id=conversation.id,
                expires_at=_expires_at(),
            )
        )
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            continue
        return conversation
    raise AppError(409, "idempotency_key_conflict", "Idempotency-Key was already used")


async def list_conversations(
    actor: Actor,
    cursor: str | None,
    limit: int,
    include_archived: bool,
    *,
    session: AsyncSession,
) -> Page[Conversation]:
    before = _cursor_or_reject(cursor)
    rows = await repository.list_conversations(
        session,
        actor.user_id,
        before=before,
        limit=limit + 1,
        include_archived=include_archived,
    )
    items = rows[:limit]
    next_cursor = _encode_cursor(items[-1].updated_at, items[-1].id) if len(rows) > limit else None
    return Page(items=items, next_cursor=next_cursor)


async def get_conversation(
    id: UUID,
    actor: Actor,
    msg_cursor: str | None,
    *,
    session: AsyncSession,
    msg_limit: int = 50,
) -> ConversationSnapshot:
    conversation = await repository.get_conversation(session, id, actor.user_id)
    if conversation is None:
        raise AppError(404, "not_found", "Conversation not found")
    after = _cursor_or_reject(msg_cursor)
    rows = await repository.list_messages(
        session, conversation.id, after=after, limit=msg_limit + 1
    )
    items = rows[:msg_limit]
    next_cursor = (
        _encode_cursor(items[-1].created_at, items[-1].id) if len(rows) > msg_limit else None
    )
    return ConversationSnapshot(conversation=conversation, messages=items, next_cursor=next_cursor)


async def patch_conversation(
    id: UUID,
    patch: ConversationPatch,
    actor: Actor,
    key: UUID,
    *,
    session: AsyncSession,
    request_hash: str,
) -> Conversation:
    operation = "patch_conversation"
    conversation = await repository.get_conversation(session, id, actor.user_id)
    if conversation is None:
        raise AppError(404, "not_found", "Conversation not found")
    for _ in range(2):
        record = await _find_valid_record(session, actor.user_id, operation, key, request_hash)
        if record is not None:
            current = await repository.get_conversation(session, id, actor.user_id)
            if current is None:
                raise AppError(404, "not_found", "Conversation not found")
            return current
        now = datetime.now(UTC)
        if patch.title is not None:
            conversation.title = patch.title
            conversation.updated_at = now
        if patch.archived is not None:
            conversation.archived_at = now if patch.archived else None
            conversation.updated_at = now
        session.add(
            IdempotencyRecord(
                user_id=actor.user_id,
                operation=operation,
                key=key,
                request_hash=request_hash,
                resource_id=conversation.id,
                expires_at=_expires_at(),
            )
        )
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            reloaded = await repository.get_conversation(session, id, actor.user_id)
            if reloaded is None:
                raise AppError(404, "not_found", "Conversation not found") from None
            conversation = reloaded
            continue
        return conversation
    raise AppError(409, "idempotency_key_conflict", "Idempotency-Key was already used")
