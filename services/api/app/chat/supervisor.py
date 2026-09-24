import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.errors import AppError
from app.chat.context import build_context
from app.chat.event_writer import (
    CompletionResult,
    SafeFailure,
    Usage,
    append_delta,
    append_usage,
    cancel_run,
    complete_run,
    fail_run,
    start_run,
)
from app.persistence.models import Message, ResponseRun
from app.providers.protocol import (
    CancelSignal,
    LlmProvider,
    ProviderDelta,
    ProviderMessage,
    ProviderStreamError,
)
from app.settings import Settings

logger = logging.getLogger(__name__)


def _failure_for(code: str, message: str) -> SafeFailure:
    return SafeFailure(code=code, message=message, retryable=code != "output_limit_exceeded")


def wait_budget_seconds(
    *,
    now: float,
    last_activity: float,
    renew_at: float,
    buffered_since: float,
    has_buffer: bool,
    idle_timeout: float,
    flush_ms: int,
    cancel_poll: float = 0.25,
) -> float:
    idle_left = idle_timeout - (now - last_activity)
    renew_left = max(renew_at - now, 0.001)
    wait = min(idle_left, renew_left, cancel_poll)
    if has_buffer:
        wait = min(wait, (flush_ms / 1000) - (now - buffered_since))
    return max(wait, 0.001)


async def _next_delta(iterator: AsyncIterator[ProviderDelta]) -> ProviderDelta | None:
    try:
        return await anext(iterator)
    except StopAsyncIteration:
        return None


class GenerationSupervisor:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        provider: LlmProvider,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._provider = provider
        self._settings = settings
        self._tasks: dict[UUID, asyncio.Task[None]] = {}
        self._admitting = True

    async def start(self, run_id: UUID) -> None:
        if not self._admitting:
            await self._safe_fail(run_id, "server_restart")
            raise RuntimeError("supervisor is shutting down")
        await self._renew_lease(run_id)
        if run_id in self._tasks:
            return
        self._tasks[run_id] = asyncio.create_task(self._run(run_id))

    async def shutdown(self, grace_seconds: float) -> None:
        self._admitting = False
        if self._tasks:
            await asyncio.wait(set(self._tasks.values()), timeout=grace_seconds)
        for run_id, task in list(self._tasks.items()):
            task.cancel()
            with contextlib.suppress(BaseException):
                await task
            await self._safe_fail(run_id, "server_restart")
            self._tasks.pop(run_id, None)
        try:
            async with self._session_factory() as session:
                leftover = list(
                    (
                        await session.scalars(
                            select(ResponseRun.id).where(
                                ResponseRun.owner_instance_id == self._settings.instance_id,
                                ResponseRun.status.in_(("queued", "streaming", "cancelling")),
                            )
                        )
                    ).all()
                )
            for run_id in leftover:
                await self._safe_fail(run_id, "server_restart")
        except Exception:
            logger.exception("shutdown leftover run sweep failed")

    async def _renew_lease(self, run_id: UUID) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                run = await session.scalar(
                    select(ResponseRun).where(ResponseRun.id == run_id).with_for_update()
                )
                if run is None:
                    raise RuntimeError(f"run {run_id} not found")
                if run.owner_instance_id != self._settings.instance_id:
                    raise RuntimeError(f"run {run_id} is not owned by this instance")
                now = datetime.now(UTC)
                run.lease_expires_at = now + timedelta(seconds=self._settings.lease_seconds)
                run.updated_at = now

    async def _run(self, run_id: UUID) -> None:
        signal = CancelSignal()
        try:
            if await self._cancel_requested(run_id):
                async with self._session_factory() as session:
                    await cancel_run(run_id, session=session)
                return
            async with self._session_factory() as session:
                await start_run(run_id, session=session)
            async with self._session_factory() as session:
                run = await session.get(ResponseRun, run_id)
                if run is None:
                    return
                context = await build_context(session, run.conversation_id, settings=self._settings)
            await self._generate(run_id, context.messages, signal)
        except asyncio.CancelledError:
            raise
        except ProviderStreamError as exc:
            await self._safe_fail(run_id, exc.error.code)
        except (AppError, SQLAlchemyError):
            logger.exception("run %s persistence failed", run_id)
            await self._safe_fail(run_id, "persistence_failed")
        except Exception:
            logger.exception("run %s failed", run_id)
            await self._safe_fail(run_id, "provider_unavailable")
        finally:
            self._tasks.pop(run_id, None)

    async def _generate(
        self, run_id: UUID, messages: list[ProviderMessage], signal: CancelSignal
    ) -> None:
        settings = self._settings
        loop = asyncio.get_running_loop()
        started = loop.time()
        last_activity = started
        renew_at = started + settings.lease_renew_seconds
        buffer: list[str] = []
        buffered_chars = 0
        buffered_since = started
        produced = 0
        usage_total: Usage | None = None
        finish_reason: str | None = None

        iterator = self._provider.stream(messages, signal=signal)
        next_task: asyncio.Task[ProviderDelta | None] = asyncio.create_task(_next_delta(iterator))
        try:
            while True:
                now = loop.time()
                if now >= renew_at:
                    await self._renew_lease(run_id)
                    renew_at = loop.time() + settings.lease_renew_seconds
                if await self._cancel_requested(run_id):
                    signal.set()
                if signal.cancelled:
                    async with self._session_factory() as session:
                        await cancel_run(run_id, session=session)
                    return
                if now - last_activity >= settings.provider_idle_timeout_seconds:
                    await self._flush(run_id, buffer)
                    await self._safe_fail(run_id, "provider_timeout")
                    return
                if now - started >= settings.generation_timeout_seconds:
                    await self._flush(run_id, buffer)
                    await self._safe_fail(run_id, "provider_timeout")
                    return
                if buffer and (now - buffered_since) * 1000 >= settings.delta_flush_ms:
                    await self._flush(run_id, buffer)
                    buffered_chars = 0
                    buffered_since = loop.time()
                wait_budget = wait_budget_seconds(
                    now=loop.time(),
                    last_activity=last_activity,
                    renew_at=renew_at,
                    buffered_since=buffered_since,
                    has_buffer=bool(buffer),
                    idle_timeout=settings.provider_idle_timeout_seconds,
                    flush_ms=settings.delta_flush_ms,
                )
                done, _ = await asyncio.wait({next_task}, timeout=wait_budget)
                if not done:
                    continue
                try:
                    delta = next_task.result()
                except ProviderStreamError as exc:
                    await self._flush(run_id, buffer)
                    await self._safe_fail(run_id, exc.error.code)
                    return
                if delta is None:
                    break
                next_task = asyncio.create_task(_next_delta(iterator))
                last_activity = loop.time()
                if delta.error is not None:
                    await self._flush(run_id, buffer)
                    await self._safe_fail(run_id, delta.error.code)
                    return
                if delta.text:
                    buffer.append(delta.text)
                    buffered_chars += len(delta.text)
                    produced += len(delta.text)
                    if produced > settings.max_output_chars:
                        await self._flush(run_id, buffer)
                        await self._safe_fail(run_id, "output_limit_exceeded")
                        return
                    if buffered_chars >= settings.delta_flush_chars:
                        await self._flush(run_id, buffer)
                        buffered_chars = 0
                        buffered_since = loop.time()
                if delta.usage is not None:
                    usage_total = delta.usage
                    async with self._session_factory() as session:
                        await append_usage(run_id, delta.usage, session=session)
                if delta.finish_reason is not None:
                    finish_reason = delta.finish_reason
                    break
        finally:
            if not next_task.done():
                next_task.cancel()
                with contextlib.suppress(BaseException):
                    await next_task
        await self._flush(run_id, buffer)
        if finish_reason is None:
            await self._safe_fail(run_id, "provider_protocol_error")
            return
        content = await self._content(run_id)
        async with self._session_factory() as session:
            await complete_run(
                run_id,
                CompletionResult(content=content, finish_reason=finish_reason, usage=usage_total),
                session=session,
            )

    async def _flush(self, run_id: UUID, buffer: list[str]) -> None:
        if not buffer:
            return
        text = "".join(buffer)
        buffer.clear()
        async with self._session_factory() as session:
            await append_delta(run_id, text, session=session)

    async def _cancel_requested(self, run_id: UUID) -> bool:
        async with self._session_factory() as session:
            requested = await session.scalar(
                select(ResponseRun.cancel_requested_at).where(ResponseRun.id == run_id)
            )
        return requested is not None

    async def _content(self, run_id: UUID) -> str:
        async with self._session_factory() as session:
            run = await session.get(ResponseRun, run_id)
            if run is None:
                return ""
            message = await session.get(Message, run.assistant_message_id)
        return message.content if message else ""

    async def _safe_fail(self, run_id: UUID, code: str) -> None:
        with contextlib.suppress(Exception):
            async with self._session_factory() as session:
                await fail_run(
                    run_id,
                    _failure_for(code, "The assistant could not finish this response."),
                    session=session,
                )
