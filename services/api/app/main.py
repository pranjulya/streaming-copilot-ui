import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from app.api.conversations import router as conversations_router
from app.api.errors import install_error_handlers
from app.api.health import router
from app.api.runs import router as runs_router
from app.chat.responses import reap_expired_leases, reap_orphaned_runs
from app.persistence.session import create_database_engine, create_session_factory
from app.settings import Settings

logger = logging.getLogger(__name__)


async def _periodic_lease_reaper(app: FastAPI, config: Settings) -> None:
    while True:
        await asyncio.sleep(config.lease_seconds)
        try:
            async with app.state.session_factory() as session:
                await reap_expired_leases(session=session, settings=config)
        except Exception:
            logger.exception("periodic lease reaper tick failed")


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_database_engine(config.database_url.get_secret_value())
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
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
            await engine.dispose()

    app = FastAPI(title="Streaming Copilot API", version="0.1.0", lifespan=lifespan)
    app.state.settings = config
    install_error_handlers(app)
    app.include_router(router)
    app.include_router(conversations_router)
    app.include_router(runs_router)
    return app
