import secrets
import time
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    desc,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def uuid7() -> UUID:
    """RFC 9562 UUIDv7: 48-bit unix-ms timestamp, time-ordered."""
    timestamp_ms = time.time_ns() // 1_000_000
    value = (
        (timestamp_ms & 0x0000FFFFFFFFFFFF) << 80
        | (7 << 76)
        | (secrets.randbits(12) << 64)
        | (0b10 << 62)
        | secrets.randbits(62)
    )
    return UUID(int=value)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index(
            "ix_conversations_user_updated_at_id",
            "user_id",
            desc("updated_at"),
            desc("id"),
        ),
        Index("ix_conversations_user_archived_at", "user_id", "archived_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=_utcnow
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("role IN ('user','assistant')", name="ck_messages_role"),
        CheckConstraint(
            "status IN ('complete','partial','cancelled','failed')", name="ck_messages_status"
        ),
        CheckConstraint(
            "role <> 'user' OR (client_message_id IS NOT NULL AND status = 'complete')",
            name="ck_messages_user_fields",
        ),
        CheckConstraint(
            "role <> 'assistant' OR in_reply_to_id IS NOT NULL",
            name="ck_messages_assistant_fields",
        ),
        Index(
            "uq_messages_conversation_client_message_id",
            "conversation_id",
            "client_message_id",
            unique=True,
            postgresql_where=text("client_message_id IS NOT NULL"),
        ),
        Index(
            "uq_messages_visible_assistant_per_reply",
            "in_reply_to_id",
            unique=True,
            postgresql_where=text("role = 'assistant' AND is_visible"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="RESTRICT")
    )
    role: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    client_message_id: Mapped[UUID | None] = mapped_column()
    in_reply_to_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="RESTRICT")
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_visible: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=_utcnow
    )


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    user_id: Mapped[str] = mapped_column(Text, primary_key=True)
    operation: Mapped[str] = mapped_column(Text, primary_key=True)
    key: Mapped[UUID] = mapped_column(primary_key=True)
    request_hash: Mapped[str] = mapped_column(Text)
    resource_id: Mapped[UUID] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=_utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
