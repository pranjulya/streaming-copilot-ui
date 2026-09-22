from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.chat.state_machine import assert_transition, is_terminal
from app.persistence.models import (
    Conversation,
    Message,
    ResponseRun,
    StreamEventRecord,
    uuid7,
)

PROTOCOL_VERSION = "1.0"


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class StreamEvent:
    protocol_version: str
    sequence: int
    event_id: UUID
    type: str
    occurred_at: datetime
    conversation_id: UUID
    run_id: UUID
    data: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "protocol_version": self.protocol_version,
            "sequence": self.sequence,
            "event_id": str(self.event_id),
            "type": self.type,
            "occurred_at": _iso(self.occurred_at),
            "conversation_id": str(self.conversation_id),
            "run_id": str(self.run_id),
            "data": self.data,
        }


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class CompletionResult:
    content: str
    finish_reason: str
    usage: Usage | None = None


@dataclass(frozen=True)
class SafeFailure:
    code: str
    message: str
    retryable: bool = True
    diagnostic_id: str | None = None


def _envelope(record: StreamEventRecord, conversation_id: UUID) -> StreamEvent:
    return StreamEvent(
        protocol_version=PROTOCOL_VERSION,
        sequence=record.sequence,
        event_id=record.event_id,
        type=record.type,
        occurred_at=record.occurred_at,
        conversation_id=conversation_id,
        run_id=record.run_id,
        data=dict(record.payload),
    )


async def _load_run_for_update(session: AsyncSession, run_id: UUID) -> ResponseRun:
    run = await session.scalar(
        select(ResponseRun).where(ResponseRun.id == run_id).with_for_update()
    )
    if run is None:
        raise AppError(404, "not_found", "Response run not found")
    return run


async def _load_message(session: AsyncSession, message_id: UUID) -> Message:
    message = await session.get(Message, message_id)
    if message is None:
        raise AppError(404, "not_found", "Message not found")
    return message


async def _load_conversation(session: AsyncSession, conversation_id: UUID) -> Conversation:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise AppError(404, "not_found", "Conversation not found")
    return conversation


async def _insert_event(
    session: AsyncSession, run: ResponseRun, event_type: str, data: dict[str, object]
) -> StreamEvent:
    now = datetime.now(UTC)
    sequence = run.last_sequence + 1
    record = StreamEventRecord(
        run_id=run.id,
        sequence=sequence,
        event_id=uuid7(),
        type=event_type,
        payload=data,
        occurred_at=now,
    )
    session.add(record)
    run.last_sequence = sequence
    run.updated_at = now
    return _envelope(record, run.conversation_id)


async def _stored_event(session: AsyncSession, run_id: UUID, event_type: str) -> StreamEvent | None:
    record = await session.scalar(
        select(StreamEventRecord)
        .where(StreamEventRecord.run_id == run_id, StreamEventRecord.type == event_type)
        .order_by(StreamEventRecord.sequence.desc())
        .limit(1)
    )
    if record is None:
        return None
    run = await session.get(ResponseRun, run_id)
    assert run is not None
    return _envelope(record, run.conversation_id)


async def start_run(run_id: UUID, *, session: AsyncSession) -> StreamEvent:
    async with session.begin():
        run = await _load_run_for_update(session, run_id)
        assert_transition(run.status, "streaming")
        now = datetime.now(UTC)
        run.status = "streaming"
        run.started_at = now
        run.updated_at = now
        user_message = await _load_message(session, run.user_message_id)
        data: dict[str, object] = {
            "user_message_id": str(run.user_message_id),
            "assistant_message_id": str(run.assistant_message_id),
            "client_message_id": str(user_message.client_message_id),
            "attempt": run.attempt,
        }
        return await _insert_event(session, run, "response.started", data)


async def append_delta(run_id: UUID, delta: str, *, session: AsyncSession) -> StreamEvent:
    async with session.begin():
        run = await _load_run_for_update(session, run_id)
        if run.status != "streaming":
            raise AppError(
                409,
                "invalid_run_state",
                "Cannot append content to a run that is not streaming",
            )
        message = await _load_message(session, run.assistant_message_id)
        content_index = len(message.content)
        message.content = message.content + delta
        message.updated_at = datetime.now(UTC)
        data: dict[str, object] = {
            "message_id": str(run.assistant_message_id),
            "delta": delta,
            "content_index": content_index,
        }
        return await _insert_event(session, run, "message.delta", data)


async def append_usage(run_id: UUID, usage: Usage, *, session: AsyncSession) -> StreamEvent:
    async with session.begin():
        run = await _load_run_for_update(session, run_id)
        if run.status != "streaming":
            raise AppError(
                409,
                "invalid_run_state",
                "Cannot record usage for a run that is not streaming",
            )
        run.input_tokens = usage.input_tokens
        run.output_tokens = usage.output_tokens
        data: dict[str, object] = {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
        }
        return await _insert_event(session, run, "usage.updated", data)


async def complete_run(
    run_id: UUID, result: CompletionResult, *, session: AsyncSession
) -> tuple[StreamEvent, StreamEvent]:
    async with session.begin():
        run = await _load_run_for_update(session, run_id)
        if is_terminal(run.status):
            if run.status != "completed":
                assert_transition(run.status, "completed")
            stored_message = await _stored_event(session, run_id, "message.completed")
            stored_response = await _stored_event(session, run_id, "response.completed")
            if stored_message is None or stored_response is None:
                raise AppError(
                    409,
                    "invalid_run_state",
                    "Terminal run is missing its committed events",
                )
            return stored_message, stored_response
        assert_transition(run.status, "completed")
        now = datetime.now(UTC)
        message = await _load_message(session, run.assistant_message_id)
        message.content = result.content
        message.status = "complete"
        message.updated_at = now
        run.status = "completed"
        run.completed_at = now
        run.updated_at = now
        if result.usage is not None:
            run.input_tokens = result.usage.input_tokens
            run.output_tokens = result.usage.output_tokens
        conversation = await _load_conversation(session, run.conversation_id)
        conversation.updated_at = now
        message_data: dict[str, object] = {
            "message_id": str(run.assistant_message_id),
            "content": result.content,
            "finish_reason": result.finish_reason,
        }
        message_event = await _insert_event(session, run, "message.completed", message_data)
        response_data: dict[str, object] = {"finish_reason": result.finish_reason}
        if result.usage is not None:
            response_data["usage"] = {
                "input_tokens": result.usage.input_tokens,
                "output_tokens": result.usage.output_tokens,
            }
        response_event = await _insert_event(session, run, "response.completed", response_data)
        return message_event, response_event


async def fail_run(run_id: UUID, failure: SafeFailure, *, session: AsyncSession) -> StreamEvent:
    async with session.begin():
        run = await _load_run_for_update(session, run_id)
        if is_terminal(run.status):
            if run.status != "failed":
                assert_transition(run.status, "failed")
            stored = await _stored_event(session, run_id, "response.failed")
            if stored is None:
                raise AppError(
                    409, "invalid_run_state", "Terminal run is missing its committed events"
                )
            return stored
        assert_transition(run.status, "failed")
        now = datetime.now(UTC)
        message = await _load_message(session, run.assistant_message_id)
        message.status = "failed"
        message.updated_at = now
        run.status = "failed"
        run.completed_at = now
        run.error_code = failure.code
        run.diagnostic_id = failure.diagnostic_id or str(uuid4())
        run.updated_at = now
        conversation = await _load_conversation(session, run.conversation_id)
        conversation.updated_at = now
        data: dict[str, object] = {
            "code": failure.code,
            "message": failure.message,
            "retryable": failure.retryable,
            "diagnostic_id": run.diagnostic_id,
            "content": message.content,
        }
        return await _insert_event(session, run, "response.failed", data)


async def cancel_run(run_id: UUID, *, session: AsyncSession) -> StreamEvent:
    async with session.begin():
        run = await _load_run_for_update(session, run_id)
        if is_terminal(run.status):
            if run.status != "cancelled":
                assert_transition(run.status, "cancelled")
            stored = await _stored_event(session, run_id, "response.cancelled")
            if stored is None:
                raise AppError(
                    409, "invalid_run_state", "Terminal run is missing its committed events"
                )
            return stored
        assert_transition(run.status, "cancelling")
        run.status = "cancelling"
        assert_transition(run.status, "cancelled")
        now = datetime.now(UTC)
        message = await _load_message(session, run.assistant_message_id)
        message.status = "cancelled"
        message.updated_at = now
        run.status = "cancelled"
        run.completed_at = now
        run.updated_at = now
        conversation = await _load_conversation(session, run.conversation_id)
        conversation.updated_at = now
        data: dict[str, object] = {
            "reason": "user_requested",
            "partial_content_retained": bool(message.content),
            "content": message.content,
        }
        return await _insert_event(session, run, "response.cancelled", data)
