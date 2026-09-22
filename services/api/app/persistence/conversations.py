from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.models import Conversation, IdempotencyRecord, Message


async def get_conversation(
    session: AsyncSession, conversation_id: UUID, user_id: str
) -> Conversation | None:
    result = await session.scalars(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
    )
    return result.one_or_none()


async def list_conversations(
    session: AsyncSession,
    user_id: str,
    *,
    before: tuple[datetime, UUID] | None,
    limit: int,
    include_archived: bool,
) -> list[Conversation]:
    statement = select(Conversation).where(Conversation.user_id == user_id)
    if not include_archived:
        statement = statement.where(Conversation.archived_at.is_(None))
    if before is not None:
        timestamp, row_id = before
        statement = statement.where(
            or_(
                Conversation.updated_at < timestamp,
                and_(Conversation.updated_at == timestamp, Conversation.id < row_id),
            )
        )
    statement = statement.order_by(desc(Conversation.updated_at), desc(Conversation.id)).limit(
        limit
    )
    return list((await session.scalars(statement)).all())


async def list_messages(
    session: AsyncSession,
    conversation_id: UUID,
    *,
    after: tuple[datetime, UUID] | None,
    limit: int,
) -> list[Message]:
    statement = select(Message).where(Message.conversation_id == conversation_id)
    if after is not None:
        timestamp, row_id = after
        statement = statement.where(
            or_(
                Message.created_at > timestamp,
                and_(Message.created_at == timestamp, Message.id > row_id),
            )
        )
    statement = statement.order_by(Message.created_at, Message.id).limit(limit)
    return list((await session.scalars(statement)).all())


async def get_idempotency(
    session: AsyncSession, user_id: str, operation: str, key: UUID
) -> IdempotencyRecord | None:
    return await session.get(IdempotencyRecord, (user_id, operation, key))


async def delete_idempotency(session: AsyncSession, record: IdempotencyRecord) -> None:
    await session.delete(record)
