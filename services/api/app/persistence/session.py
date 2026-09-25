import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.observability.metrics import DB_TX_SECONDS


def create_database_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(
        database_url,
        pool_pre_ping=True,
        pool_timeout=2,
        connect_args={"timeout": 2, "command_timeout": 2},
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        yield session


@asynccontextmanager
async def db_transaction(session: AsyncSession, op: str) -> AsyncIterator[None]:
    """A `session.begin()` unit of work that records its latency under a bounded op."""
    started = time.perf_counter()
    try:
        async with session.begin():
            yield
    finally:
        DB_TX_SECONDS.labels(op=op).observe(time.perf_counter() - started)
