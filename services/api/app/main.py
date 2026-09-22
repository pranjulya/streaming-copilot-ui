from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.conversations import router as conversations_router
from app.api.errors import install_error_handlers
from app.api.health import router
from app.persistence.session import create_database_engine, create_session_factory
from app.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_database_engine(config.database_url.get_secret_value())
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(title="Streaming Copilot API", version="0.1.0", lifespan=lifespan)
    app.state.settings = config
    install_error_handlers(app)
    app.include_router(router)
    app.include_router(conversations_router)
    return app
