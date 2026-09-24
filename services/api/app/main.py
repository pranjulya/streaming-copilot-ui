import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request, Response

from app.api.body_limit import RequestBodyLimitMiddleware
from app.api.conversations import router as conversations_router
from app.api.dev import router as dev_router
from app.api.errors import install_error_handlers
from app.api.health import router
from app.api.responses import router as responses_router
from app.api.runs import router as runs_router
from app.chat.event_writer import compact_expired_events
from app.chat.responses import reap_expired_leases, reap_orphaned_runs
from app.chat.supervisor import GenerationSupervisor
from app.persistence.session import create_database_engine, create_session_factory
from app.providers.protocol import LlmProvider
from app.settings import Settings

logger = logging.getLogger(__name__)

# Client-supplied correlation IDs must be short and log-safe; anything else is replaced.
_REQUEST_ID_PATTERN = re.compile(r"\A[A-Za-z0-9._:-]{1,128}\Z")


def _build_provider(config: Settings) -> LlmProvider:
    from app.providers.fake import FakeProvider, planned_provider_from_steps

    has_key = bool(config.xai_api_key and config.xai_api_key.get_secret_value().strip())
    if config.app_env == "development" and not has_key:
        long_delay = config.fake_provider_long_delay_seconds
        plan = config.fake_provider_plan.strip()
        if plan:
            return planned_provider_from_steps(
                json.loads(plan), long_delay_seconds=long_delay
            )
        return FakeProvider(
            deltas=[
                "This is the local fake provider. ",
                "Set XAI_API_KEY to stream real model output.",
            ],
            finish_reason="stop",
            long_delay_seconds=long_delay,
        )
    from app.providers.xai import XaiProvider

    return XaiProvider(config)


async def _periodic_lease_reaper(app: FastAPI, config: Settings) -> None:
    while True:
        await asyncio.sleep(config.lease_seconds)
        try:
            async with app.state.session_factory() as session:
                await reap_expired_leases(session=session, settings=config)
                await compact_expired_events(
                    session=session, retention_hours=config.event_retention_hours
                )
        except Exception:
            logger.exception("periodic lease reaper tick failed")


def install_cors(app: FastAPI, config: Settings) -> None:
    from fastapi.middleware.cors import CORSMiddleware

    origins = [item.strip() for item in config.allowed_origins.split(",") if item.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "X-CSRF-Token",
            "X-Dev-User",
        ],
        expose_headers=["X-Request-ID"],
    )


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
        from app.api.auth_jwt import JwtVerifier

        app.state.jwt_verifier = JwtVerifier(config)
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
    install_observability(app, config)
    install_cors(app, config)
    app.add_middleware(RequestBodyLimitMiddleware, max_bytes=config.max_request_bytes)
    app.include_router(router)
    app.include_router(conversations_router)
    app.include_router(runs_router)
    app.include_router(responses_router)
    if config.app_env == "development":
        app.include_router(dev_router)
    return app


def install_observability(app: FastAPI, config: Settings) -> None:
    from app.observability.logging import (
        configure_logging,
        new_request_id,
        new_trace_id,
        request_id_var,
        trace_id_var,
    )
    from app.observability.metrics import (
        ACCEPT_LATENCY_SECONDS,
        HTTP_REQUESTS_TOTAL,
        METRICS_CONTENT_TYPE,
        render_metrics,
    )

    configure_logging(config.log_level)

    @app.middleware("http")
    async def correlate_requests(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = _client_request_id(request.headers.get("x-request-id")) or new_request_id()
        trace_id = new_trace_id()
        request_id_var.set(request_id)
        trace_id_var.set(trace_id)
        request.state.request_id = request_id
        request.state.trace_id = trace_id
        started = asyncio.get_running_loop().time()
        request.state.accepted_at = started
        try:
            response = await call_next(request)
        finally:
            elapsed = asyncio.get_running_loop().time() - started
            ACCEPT_LATENCY_SECONDS.labels(endpoint=_endpoint_label(request)).observe(elapsed)
        response.headers["X-Request-ID"] = request_id
        problem_code = response.headers.get("x-problem-code", "")
        if "x-problem-code" in response.headers:
            del response.headers["x-problem-code"]
        HTTP_REQUESTS_TOTAL.labels(
            endpoint=_endpoint_label(request),
            status=str(response.status_code),
            code=problem_code,
        ).inc()
        return response

    @app.get("/metrics", include_in_schema=False)
    async def metrics_endpoint() -> Response:
        return Response(content=render_metrics(), media_type=METRICS_CONTENT_TYPE)


def _client_request_id(raw: str | None) -> str | None:
    """Accept a caller-supplied request ID only when it is short and log-safe."""
    if raw is not None and _REQUEST_ID_PATTERN.match(raw):
        return raw
    return None


def _endpoint_label(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    # Fall back to a fixed label so unmapped paths cannot explode metric cardinality.
    return str(path) if path else "unmatched"
