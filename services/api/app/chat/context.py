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
    included = [
        ProviderMessage(role=message.role, content=message.content)
        for message in rows
        if _include(message)
    ]
    turns = _group_turns(included)
    total = sum(len(message.content) for turn in turns for message in turn)
    dropped = 0
    while total > settings.context_char_budget and len(turns) > 1:
        removed = turns.pop(0)
        total -= sum(len(message.content) for message in removed)
        dropped += 1
    if dropped:
        logger.info("context window trimmed: dropped %d context turns", dropped)
    flattened = [message for turn in turns for message in turn]
    messages = [ProviderMessage(role="system", content=settings.system_prompt), *flattened]
    return ContextResult(messages=messages, dropped_turns=dropped)


def _group_turns(messages: list[ProviderMessage]) -> list[list[ProviderMessage]]:
    turns: list[list[ProviderMessage]] = []
    index = 0
    while index < len(messages):
        if messages[index].role == "user":
            turn = [messages[index]]
            index += 1
            if index < len(messages) and messages[index].role == "assistant":
                turn.append(messages[index])
                index += 1
            turns.append(turn)
        else:
            turns.append([messages[index]])
            index += 1
    return turns
