import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import Actor, require_actor
from app.api.errors import AppError
from app.chat.conversations import (
    ConversationPatch,
    CreateConversation,
    create_conversation,
    get_conversation,
    list_conversations,
    patch_conversation,
)
from app.persistence.models import Conversation, Message
from app.persistence.session import get_session

router = APIRouter(prefix="/v1/conversations", tags=["conversations"])

CREATE_OPERATION_LIMITS = (1, 100)


def _require_idempotency_key(request: Request) -> UUID:
    raw = request.headers.get("idempotency-key")
    if raw is None:
        raise AppError(400, "validation_failed", "Idempotency-Key header is required")
    try:
        return UUID(raw)
    except ValueError:
        raise AppError(400, "validation_failed", "Idempotency-Key must be a UUID") from None


def _fingerprint(raw_body: bytes, method: str, path: str) -> str:
    return hashlib.sha256(raw_body + b"\n" + method.encode() + b"\n" + path.encode()).hexdigest()


def _parse_json_object(raw_body: bytes) -> dict[str, object]:
    if not raw_body.strip():
        return {}
    try:
        parsed = json.loads(raw_body)
    except (ValueError, UnicodeDecodeError):
        raise AppError(400, "validation_failed", "Request body must be valid JSON") from None
    if not isinstance(parsed, dict):
        raise AppError(400, "validation_failed", "Request body must be a JSON object")
    return parsed


def _validated_title(value: object) -> str:
    if not isinstance(value, str):
        raise AppError(400, "validation_failed", "title must be a string")
    title = value.strip()
    if not title:
        raise AppError(400, "validation_failed", "title must not be empty")
    if len(title) > 120:
        raise AppError(400, "validation_failed", "title must be at most 120 characters")
    return title


def _validated_limit(limit: int, maximum: int) -> int:
    if limit < 1 or limit > maximum:
        raise AppError(400, "validation_failed", f"limit must be between 1 and {maximum}")
    return limit


def _rfc3339(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def conversation_dict(conversation: Conversation) -> dict[str, object]:
    return {
        "id": str(conversation.id),
        "title": conversation.title,
        "created_at": _rfc3339(conversation.created_at),
        "updated_at": _rfc3339(conversation.updated_at),
        "archived_at": _rfc3339(conversation.archived_at) if conversation.archived_at else None,
        "active_run_id": None,
    }


def message_dict(message: Message) -> dict[str, object]:
    return {
        "id": str(message.id),
        "conversation_id": str(message.conversation_id),
        "role": message.role,
        "content": message.content,
        "status": message.status,
        "client_message_id": str(message.client_message_id) if message.client_message_id else None,
        "in_reply_to_id": str(message.in_reply_to_id) if message.in_reply_to_id else None,
        "version": message.version,
        "is_visible": message.is_visible,
        "created_at": _rfc3339(message.created_at),
    }


@router.post("", status_code=201)
async def create_conversation_route(
    request: Request,
    actor: Actor = Depends(require_actor),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    raw_body = await request.body()
    body = _parse_json_object(raw_body)
    unknown = set(body) - {"title"}
    if unknown:
        raise AppError(400, "validation_failed", "Request body contains unknown fields")
    cmd = CreateConversation(
        title=_validated_title(body["title"]) if "title" in body else None,
        idempotency_key=_require_idempotency_key(request),
        request_hash=_fingerprint(raw_body, "POST", request.url.path),
    )
    conversation = await create_conversation(cmd, actor, session=session)
    return conversation_dict(conversation)


@router.get("")
async def list_conversations_route(
    cursor: str | None = None,
    limit: int = 20,
    include_archived: bool = False,
    actor: Actor = Depends(require_actor),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    _validated_limit(limit, maximum=100)
    page = await list_conversations(actor, cursor, limit, include_archived, session=session)
    return {
        "items": [conversation_dict(conversation) for conversation in page.items],
        "next_cursor": page.next_cursor,
    }


@router.get("/{conversation_id}")
async def get_conversation_route(
    conversation_id: UUID,
    cursor: str | None = None,
    limit: int = 50,
    actor: Actor = Depends(require_actor),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    _validated_limit(limit, maximum=100)
    snapshot = await get_conversation(
        conversation_id, actor, cursor, session=session, msg_limit=limit
    )
    return {
        "conversation": conversation_dict(snapshot.conversation),
        "messages": {
            "items": [message_dict(message) for message in snapshot.messages],
            "next_cursor": snapshot.next_cursor,
        },
        "active_run": None,
    }


@router.patch("/{conversation_id}")
async def patch_conversation_route(
    conversation_id: UUID,
    request: Request,
    actor: Actor = Depends(require_actor),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    raw_body = await request.body()
    body = _parse_json_object(raw_body)
    if not body:
        raise AppError(400, "validation_failed", "At least one field is required")
    unknown = set(body) - {"title", "archived"}
    if unknown:
        raise AppError(400, "validation_failed", "Request body contains unknown fields")
    if "archived" in body and not isinstance(body["archived"], bool):
        raise AppError(400, "validation_failed", "archived must be a boolean")
    patch = ConversationPatch(
        title=_validated_title(body["title"]) if "title" in body else None,
        archived=body["archived"] if "archived" in body else None,  # type: ignore[arg-type]
    )
    conversation = await patch_conversation(
        conversation_id,
        patch,
        actor,
        _require_idempotency_key(request),
        session=session,
        request_hash=_fingerprint(raw_body, "PATCH", request.url.path),
    )
    return conversation_dict(conversation)
