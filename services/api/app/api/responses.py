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
from app.api.bounds import enforce_send_rate, low_quota_rate_limit_headers
from app.api.errors import AppError
from app.api.requests import fingerprint, read_json_body, require_idempotency_key
from app.chat.event_writer import follow_events
from app.chat.responses import (
    CreateResponse,
    create_response,
    get_run,
    regenerate_message,
    retry_run,
)
from app.observability.metrics import (
    RECONNECT_CATCHUP_SECONDS,
    SERVICE_FIRST_EVENT_SECONDS,
    STREAM_BYTES_TOTAL,
)
from app.persistence.models import ResponseRun
from app.settings import Settings

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = ("completed", "cancelled", "failed")
NDJSON_MEDIA_TYPE = "application/x-ndjson; charset=utf-8"

router = APIRouter(prefix="/v1", tags=["responses"])


def _ndjson_response(
    events: AsyncIterator[bytes], headers: dict[str, str] | None = None
) -> StreamingResponse:
    response_headers = {"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"}
    if headers:
        response_headers.update(headers)
    return StreamingResponse(
        events,
        media_type=NDJSON_MEDIA_TYPE,
        headers=response_headers,
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
    *,
    accepted_at: float | None = None,
    reconnect_started_at: float | None = None,
) -> AsyncIterator[bytes]:
    cursor = after_sequence
    loop = asyncio.get_running_loop()
    last_emit = loop.time()
    first_event_seen = False
    catchup_target: int | None = None
    catchup_observed = False
    while True:
        async with session_factory() as session:
            events = await follow_events(run_id, cursor, session=session)
            run = await session.get(ResponseRun, run_id)
        if reconnect_started_at is not None and catchup_target is None and run is not None:
            # Everything committed at reconnect time is the follower's catch-up target.
            catchup_target = run.last_sequence
        for event in events:
            cursor = max(cursor, event.sequence)
            chunk = (json.dumps(event.to_dict()) + "\n").encode("utf-8")
            STREAM_BYTES_TOTAL.inc(len(chunk))
            if not first_event_seen:
                first_event_seen = True
                if accepted_at is not None and run is not None:
                    SERVICE_FIRST_EVENT_SECONDS.labels(model=run.model or "").observe(
                        loop.time() - accepted_at
                    )
            yield chunk
            last_emit = loop.time()
        if (
            reconnect_started_at is not None
            and not catchup_observed
            and catchup_target is not None
            and cursor >= catchup_target
        ):
            RECONNECT_CATCHUP_SECONDS.observe(loop.time() - reconnect_started_at)
            catchup_observed = True
        if run is None:
            return
        if run.status in TERMINAL_STATUSES and not events:
            return
        if loop.time() - last_emit >= settings.heartbeat_interval_seconds:
            heartbeat = _heartbeat_line(run)
            STREAM_BYTES_TOTAL.inc(len(heartbeat))
            yield heartbeat
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


def _ndjson_follow(
    request: Request,
    run_id: UUID,
    after_sequence: int,
    *,
    accepted_at: float | None = None,
    reconnect_started_at: float | None = None,
    include_rate_limit_headers: bool = False,
) -> StreamingResponse:
    settings: Settings = request.app.state.settings
    return _ndjson_response(
        _follow(
            request.app.state.session_factory,
            run_id,
            after_sequence,
            settings,
            accepted_at=accepted_at,
            reconnect_started_at=reconnect_started_at,
        ),
        headers=(low_quota_rate_limit_headers(request) if include_rate_limit_headers else None),
    )


async def _start_and_follow(
    request: Request,
    run: ResponseRun,
    accepted_at: float | None = None,
) -> StreamingResponse:
    await _ensure_generation(request, run)
    return _ndjson_follow(
        request,
        run.id,
        0,
        accepted_at=accepted_at,
        include_rate_limit_headers=True,
    )


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


@router.post("/conversations/{conversation_id}/responses")
async def create_response_and_stream(
    conversation_id: UUID,
    request: Request,
    actor: Actor = Depends(require_actor),
) -> StreamingResponse:
    raw_body, body = await read_json_body(request, {"client_message_id", "content"})
    enforce_send_rate(request, actor.user_id)
    accepted_at = getattr(request.state, "accepted_at", None)
    settings: Settings = request.app.state.settings
    cmd = CreateResponse(
        conversation_id=conversation_id,
        client_message_id=_client_message_id(body),
        content=_validated_content(body),
        idempotency_key=require_idempotency_key(request),
        request_hash=fingerprint(raw_body, "POST", request.url.path),
    )
    async with request.app.state.session_factory() as session:
        run = await create_response(cmd, actor, session=session, settings=settings)
    return await _start_and_follow(request, run, accepted_at)


@router.post("/response-runs/{run_id}/stream")
async def stream_response_run(
    run_id: UUID,
    request: Request,
    actor: Actor = Depends(require_actor),
) -> StreamingResponse:
    _, body = await read_json_body(request, {"after_sequence"})
    async with request.app.state.session_factory() as session:
        await get_run(run_id, actor, session=session)
    return _ndjson_follow(
        request,
        run_id,
        _after_sequence(body),
        reconnect_started_at=asyncio.get_running_loop().time(),
    )


@router.post("/response-runs/{run_id}/retry")
async def retry_response_run(
    run_id: UUID,
    request: Request,
    actor: Actor = Depends(require_actor),
) -> StreamingResponse:
    raw_body, _ = await read_json_body(request, set())
    enforce_send_rate(request, actor.user_id)
    accepted_at = getattr(request.state, "accepted_at", None)
    settings: Settings = request.app.state.settings
    async with request.app.state.session_factory() as session:
        run = await retry_run(
            run_id,
            actor,
            session=session,
            settings=settings,
            idempotency_key=require_idempotency_key(request),
            request_hash=fingerprint(raw_body, "POST", request.url.path),
        )
    return await _start_and_follow(request, run, accepted_at)


@router.post("/messages/{user_message_id}/regenerations")
async def regenerate_message_and_stream(
    user_message_id: UUID,
    request: Request,
    actor: Actor = Depends(require_actor),
) -> StreamingResponse:
    raw_body, _ = await read_json_body(request, set())
    enforce_send_rate(request, actor.user_id)
    accepted_at = getattr(request.state, "accepted_at", None)
    settings: Settings = request.app.state.settings
    async with request.app.state.session_factory() as session:
        run = await regenerate_message(
            user_message_id,
            actor,
            session=session,
            settings=settings,
            idempotency_key=require_idempotency_key(request),
            request_hash=fingerprint(raw_body, "POST", request.url.path),
        )
    return await _start_and_follow(request, run, accepted_at)
