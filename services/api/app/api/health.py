import asyncpg
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.settings import settings


router = APIRouter()
engine: AsyncEngine = create_async_engine(settings.database_url)


@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "live"}


@router.get("/health/ready")
async def ready():
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except (OSError, SQLAlchemyError, asyncpg.PostgresError):
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "database": "error", "code": "service_unavailable"},
            media_type="application/problem+json",
        )

    return {"status": "ready", "database": "ok"}
