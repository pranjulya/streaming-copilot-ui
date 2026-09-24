import asyncio
import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api import rfc3339
from app.api.auth import Actor, require_actor
from app.api.conversations import (
    _fingerprint,
    _parse_json_object,
    _require_idempotency_key,
)
from app.api.errors import AppError
from app.chat.event_writer import follow_events
from app.chat.responses import (
    CreateResponse,
    create_response,
    get_run,
    regenerate_message,
    retry_run,
)
from app.persistence.models import ResponseRun
from app.settings import Settings

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = ("completed", "cancelled", "failed")
NDJSON_MEDIA_TYPE = "application/x-ndjson; charset=utf-8"

router = APIRouter(prefix="/v1", tags=["responses"])


def _ndjson_response(events: AsyncIterator[bytes]) -> StreamingResponse:
    return StreamingResponse(
        events,
        media_type=NDJSON_MEDIA_TYPE,
        headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"},
    )


def _heartbeat_line(run: ResponseRun) -> bytes:
    envelope = {
        "protocol_version": "1.0",
        "sequence": run.last_sequence,
        "event_id": str(uuid4()),
        "type": "heartbeat",
        "occurred_at": rfc3339(datetime.now(UTC)),
        "conversation_id": str(run.conversation_id),
        "run_id": str(run.id),
        "data": {"last_sequence": run.last_sequence},
    }
    return (json.dumps(envelope) + "\n").encode("utf-8")


async def _follow(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: UUID,
    after_sequence: int,
    settings: Settings,
) -> AsyncIterator[bytes]:
    cursor = after_sequence
    loop = asyncio.get_running_loop()
    last_emit = loop.time()
    while True:
        async with session_factory() as session:
            events = await follow_events(run_id, cursor, session=session)
            run = await session.get(ResponseRun, run_id)
        for event in events:
            cursor = max(cursor, event.sequence)
            yield (json.dumps(event.to_dict()) + "\n").encode("utf-8")
            last_emit = loop.time()
        if run is None:
            return
        if run.status in TERMINAL_STATUSES and not events:
            return
        if loop.time() - last_emit >= settings.heartbeat_interval_seconds:
            yield _heartbeat_line(run)
            last_emit = loop.time()
        await asyncio.sleep(settings.event_follow_poll_ms / 1000)


async def _ensure_generation(request: Request, run: ResponseRun) -> None:
    if run.status != "queued":
        return
    supervisor = request.app.state.supervisor
    try:
        await supervisor.start(run.id)
    except RuntimeError as exc:
        logger.warning("run %s was not started: %s", run.id, exc)


def _client_message_id(body: dict[str, object]) -> UUID:
    raw = body.get("client_message_id")
    if not isinstance(raw, str):
        raise AppError(400, "validation_failed", "client_message_id must be a UUID string")
    try:
        return UUID(raw)
    except ValueError:
        raise AppError(400, "validation_failed", "client_message_id must be a UUID") from None


def _validated_content(body: dict[str, object]) -> str:
    content = body.get("content")
    if not isinstance(content, str):
        raise AppError(400, "validation_failed", "content must be a string")
    return content


def _after_sequence(body: dict[str, object]) -> int:
    value = body.get("after_sequence", 0)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise AppError(400, "validation_failed", "after_sequence must be an integer >= 0")
    return value


def _reject_unknown(body: dict[str, object], allowed: set[str]) -> None:
    if set(body) - allowed:
        raise AppError(400, "validation_failed", "Request body contains unknown fields")


@router.post("/conversations/{conversation_id}/responses")
async def create_response_and_stream(
    conversation_id: UUID,
    request: Request,
    actor: Actor = Depends(require_actor),
) -> StreamingResponse:
    raw_body = await request.body()
    body = _parse_json_object(raw_body)
    _reject_unknown(body, {"client_message_id", "content"})
    settings: Settings = request.app.state.settings
    cmd = CreateResponse(
        conversation_id=conversation_id,
        client_message_id=_client_message_id(body),
        content=_validated_content(body),
        idempotency_key=_require_idempotency_key(request),
        request_hash=_fingerprint(raw_body, "POST", request.url.path),
    )
    async with request.app.state.session_factory() as session:
        run = await create_response(cmd, actor, session=session, settings=settings)
    await _ensure_generation(request, run)
    return _ndjson_response(_follow(request.app.state.session_factory, run.id, 0, settings))


@router.post("/response-runs/{run_id}/stream")
async def stream_response_run(
    run_id: UUID,
    request: Request,
    actor: Actor = Depends(require_actor),
) -> StreamingResponse:
    raw_body = await request.body()
    body = _parse_json_object(raw_body)
    _reject_unknown(body, {"after_sequence"})
    async with request.app.state.session_factory() as session:
        await get_run(run_id, actor, session=session)
    settings: Settings = request.app.state.settings
    return _ndjson_response(
        _follow(request.app.state.session_factory, run_id, _after_sequence(body), settings)
    )


@router.post("/response-runs/{run_id}/retry")
async def retry_response_run(
    run_id: UUID,
    request: Request,
    actor: Actor = Depends(require_actor),
) -> StreamingResponse:
    raw_body = await request.body()
    body = _parse_json_object(raw_body)
    _reject_unknown(body, set())
    settings: Settings = request.app.state.settings
    async with request.app.state.session_factory() as session:
        run = await retry_run(
            run_id,
            actor,
            session=session,
            settings=settings,
            idempotency_key=_require_idempotency_key(request),
            request_hash=_fingerprint(raw_body, "POST", request.url.path),
        )
    await _ensure_generation(request, run)
    return _ndjson_response(_follow(request.app.state.session_factory, run.id, 0, settings))


@router.post("/messages/{user_message_id}/regenerations")
async def regenerate_message_and_stream(
    user_message_id: UUID,
    request: Request,
    actor: Actor = Depends(require_actor),
) -> StreamingResponse:
    raw_body = await request.body()
    body = _parse_json_object(raw_body)
    _reject_unknown(body, set())
    settings: Settings = request.app.state.settings
    async with request.app.state.session_factory() as session:
        run = await regenerate_message(
            user_message_id,
            actor,
            session=session,
            settings=settings,
            idempotency_key=_require_idempotency_key(request),
            request_hash=_fingerprint(raw_body, "POST", request.url.path),
        )
    await _ensure_generation(request, run)
    return _ndjson_response(_follow(request.app.state.session_factory, run.id, 0, settings))
