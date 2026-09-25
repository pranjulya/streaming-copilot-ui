import asyncio
import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="Set TEST_DATABASE_URL for real Postgres"
)

from tests.support import writer_factory  # noqa: E402
from tests.test_retry_regenerate import seed_turn  # noqa: E402


def test_follow_events_returns_only_events_after_cursor() -> None:
    from app.chat.event_writer import append_delta, follow_events, start_run

    async def scenario() -> None:
        _, _, _, _, run_id = await seed_turn(prefix="replay")
        factory = writer_factory()
        async with factory() as session:
            await start_run(run_id, session=session)
        for delta in ("one ", "two ", "three ", "four"):
            async with factory() as session:
                await append_delta(run_id, delta, session=session)

        async with factory() as session:
            events = await follow_events(run_id, 2, session=session)
        assert [event.sequence for event in events] == [3, 4, 5]
        assert [event.data["delta"] for event in events] == ["two ", "three ", "four"]
        assert all(event.type == "message.delta" for event in events)

        async with factory() as session:
            from_start = await follow_events(run_id, 0, session=session)
        assert [event.sequence for event in from_start] == [1, 2, 3, 4, 5]
        assert from_start[0].type == "response.started"

    asyncio.run(scenario())


def test_follow_events_synthesizes_snapshot_when_events_were_compacted() -> None:
    from sqlalchemy import text

    from app.chat.event_writer import (
        CompletionResult,
        append_delta,
        complete_run,
        follow_events,
        start_run,
    )

    async def scenario() -> None:
        _, _, _, _, run_id = await seed_turn(prefix="compact")
        factory = writer_factory()
        async with factory() as session:
            await start_run(run_id, session=session)
        for index in range(7):
            async with factory() as session:
                await append_delta(run_id, f"d{index} ", session=session)
        canonical = "d0 d1 d2 d3 d4 d5 d6 final"
        async with factory() as session:
            await complete_run(
                run_id, CompletionResult(content=canonical, finish_reason="stop"), session=session
            )

        async with factory() as session:
            async with session.begin():
                await session.execute(
                    text("DELETE FROM stream_events WHERE run_id = :id"), {"id": run_id}
                )

        async with factory() as session:
            events = await follow_events(run_id, 4, session=session)
        assert len(events) == 1
        snapshot = events[0]
        assert snapshot.type == "response.snapshot"
        assert snapshot.sequence == 10
        assert snapshot.data["last_sequence"] == 10
        assert snapshot.data["content"] == canonical
        assert snapshot.data["status"] == "completed"
        assert snapshot.data["assistant_message_id"]
        assert snapshot.data["user_message_id"]

        async with factory() as session:
            up_to_date = await follow_events(run_id, 10, session=session)
        assert up_to_date == []

    asyncio.run(scenario())
