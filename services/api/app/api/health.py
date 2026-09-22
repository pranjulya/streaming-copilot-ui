import asyncio
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "live"}


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    engine: AsyncEngine = request.app.state.engine
    try:
        async with asyncio.timeout(3), engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        # Driver connection failures are not always wrapped by SQLAlchemy.
        # Every failed readiness probe is unavailable; cancellation still propagates.
        return JSONResponse(
            status_code=503,
            media_type="application/problem+json",
            content={
                "type": "https://copilot.local/problems/service_unavailable",
                "title": "Database is not ready",
                "status": "not_ready",
                "database": "error",
                "code": "service_unavailable",
                "diagnostic_id": str(uuid4()),
            },
        )
    return JSONResponse({"status": "ready", "database": "ok"})
