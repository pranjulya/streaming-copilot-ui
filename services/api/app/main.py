import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from app.api.conversations import router as conversations_router
from app.api.dev import router as dev_router
from app.api.errors import install_error_handlers
from app.api.health import router
from app.api.responses import router as responses_router
from app.api.runs import router as runs_router
from app.chat.responses import reap_expired_leases, reap_orphaned_runs
from app.chat.supervisor import GenerationSupervisor
from app.persistence.session import create_database_engine, create_session_factory
from app.providers.protocol import LlmProvider
from app.settings import Settings

logger = logging.getLogger(__name__)


def _build_provider(config: Settings) -> LlmProvider:
    from app.providers.fake import FakeProvider, PlannedFakeProvider

    has_key = bool(config.xai_api_key and config.xai_api_key.get_secret_value().strip())
    if config.app_env == "development" and not has_key:
        plan = os.environ.get("FAKE_PROVIDER_PLAN", "").strip()
        if plan:
            steps = [
                FakeProvider(
                    deltas=step.get("deltas", []),
                    finish_reason=step.get("finish_reason", "stop"),
                    fail_after=step.get("fail_after"),
                    delay_seconds=float(step.get("delay_seconds", 0.0)),
                )
                for step in json.loads(plan)
            ]
            return PlannedFakeProvider(steps)
        return FakeProvider(
            deltas=[
                "This is the local fake provider. ",
                "Set XAI_API_KEY to stream real model output.",
            ],
            finish_reason="stop",
        )
    from app.providers.xai import XaiProvider

    return XaiProvider(config)


async def _periodic_lease_reaper(app: FastAPI, config: Settings) -> None:
    while True:
        await asyncio.sleep(config.lease_seconds)
        try:
            async with app.state.session_factory() as session:
                await reap_expired_leases(session=session, settings=config)
        except Exception:
            logger.exception("periodic lease reaper tick failed")


def create_app(settings: Settings | None = None, provider: LlmProvider | None = None) -> FastAPI:
    config = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_database_engine(config.database_url.get_secret_value())
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        app.state.supervisor = GenerationSupervisor(
            session_factory=app.state.session_factory,
            provider=provider if provider is not None else _build_provider(config),
            settings=config,
        )
        try:
            async with app.state.session_factory() as session:
                await reap_orphaned_runs(session=session, settings=config)
        except Exception:
            logger.exception("startup lease reaper skipped: database unavailable")
        reaper = asyncio.create_task(_periodic_lease_reaper(app, config))
        try:
            yield
        finally:
            reaper.cancel()
            with suppress(asyncio.CancelledError):
                await reaper
            await app.state.supervisor.shutdown(config.shutdown_grace_seconds)
            app.state.supervisor = None
            await engine.dispose()

    app = FastAPI(title="Streaming Copilot API", version="0.1.0", lifespan=lifespan)
    app.state.settings = config
    install_error_handlers(app)
    app.include_router(router)
    app.include_router(conversations_router)
    app.include_router(runs_router)
    app.include_router(responses_router)
    app.include_router(dev_router)
    return app
