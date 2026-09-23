import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.models import Message
from app.providers.protocol import ProviderMessage
from app.settings import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContextResult:
    messages: list[ProviderMessage]
    dropped_turns: int


def _include(message: Message) -> bool:
    if message.role == "user":
        return True
    if message.role != "assistant":
        return False
    return message.is_visible and bool(message.content.strip())


async def build_context(
    session: AsyncSession, conversation_id: UUID, *, settings: Settings
) -> ContextResult:
    rows = (
        await session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at, Message.id)
        )
    ).all()
    turns = [
        ProviderMessage(role=message.role, content=message.content)
        for message in rows
        if _include(message)
    ]
    total = sum(len(turn.content) for turn in turns)
    dropped = 0
    while total > settings.context_char_budget and len(turns) > 1:
        total -= len(turns[0].content)
        turns.pop(0)
        dropped += 1
    if dropped:
        logger.info("context window trimmed: dropped %d context messages", dropped)
    messages = [ProviderMessage(role="system", content=settings.system_prompt), *turns]
    return ContextResult(messages=messages, dropped_turns=dropped)
