"""Load rehearsal: the configuration.md §6 mix against the local fake provider.

Run the API first with a slow fake plan, e.g.:

    FAKE_PROVIDER_PLAN='[{"deltas": ["token "] * 100, "delay_seconds": 0.02}]' \
    uv run --project services/api uvicorn app.main:create_app --factory \
        --app-dir services/api --host 127.0.0.1 --port 8000

then:

    uv run --project services/api python services/api/tests/load/load_stream_mix.py

This is a rehearsal harness, not a benchmark: it records accept latency,
first-event latency, cancel acknowledgement, reconnect catch-up, database pool
errors, and per-process RSS so Phase 08 can calibrate defaults honestly.
"""

import argparse
import asyncio
import json
import os
import statistics
import time
import uuid

import httpx
import psutil

API = os.environ.get("LOAD_API", "http://127.0.0.1:8000")
DEV_USER = os.environ.get("LOAD_USER", "load-harness")
HEADERS = {"X-Dev-User": DEV_USER}


async def create_conversation(client: httpx.AsyncClient) -> str:
    response = await client.post(
        "/v1/conversations",
        json={},
        headers={**HEADERS, "Idempotency-Key": str(uuid.uuid4())},
    )
    response.raise_for_status()
    return str(response.json()["id"])


async def stream_turn(
    client: httpx.AsyncClient, conversation_id: str, *, cancel_after: float | None
) -> dict[str, float]:
    started = time.perf_counter()
    accept_at: float | None = None
    first_event_at: float | None = None
    first_delta_at: float | None = None
    cancel_ack_at: float | None = None
    run_id: str | None = None
    events = 0

    async with client.stream(
        "POST",
        f"/v1/conversations/{conversation_id}/responses",
        json={"client_message_id": str(uuid.uuid4()), "content": "load rehearsal"},
        headers={**HEADERS, "Idempotency-Key": str(uuid.uuid4())},
    ) as response:
        response.raise_for_status()
        accept_at = time.perf_counter()
        buffer = ""
        async for chunk in response.aiter_bytes():
            buffer += chunk.decode("utf-8")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                if not line:
                    continue
                event = json.loads(line)
                events += 1
                now = time.perf_counter()
                if first_event_at is None:
                    first_event_at = now
                if run_id is None:
                    run_id = event["run_id"]
                if event["type"] == "message.delta" and first_delta_at is None:
                    first_delta_at = now
                if cancel_after is not None and now - started >= cancel_after:
                    break
            if cancel_after is not None and time.perf_counter() - started >= cancel_after:
                break

    if cancel_after is not None and run_id is not None:
        cancel_started = time.perf_counter()
        await client.post(f"/v1/response-runs/{run_id}/cancel", json={}, headers=HEADERS)
        while time.perf_counter() - cancel_started < 30:
            run = (await client.get(f"/v1/response-runs/{run_id}", headers=HEADERS)).json()
            if run["status"] in ("completed", "cancelled", "failed"):
                cancel_ack_at = time.perf_counter()
                break
            await asyncio.sleep(0.05)

    return {
        "accept_ms": (accept_at - started) * 1000 if accept_at else -1,
        "first_event_ms": (first_event_at - started) * 1000 if first_event_at else -1,
        "first_delta_ms": ((first_delta_at - started) * 1000 if first_delta_at else -1),
        "cancel_ack_ms": ((cancel_ack_at - cancel_started) * 1000 if cancel_ack_at else -1),
        "total_ms": (time.perf_counter() - started) * 1000,
        "events": events,
    }


async def reconnect_probe(client: httpx.AsyncClient) -> dict[str, float]:
    conversation_id = await create_conversation(client)
    run_id: str | None = None
    async with client.stream(
        "POST",
        f"/v1/conversations/{conversation_id}/responses",
        json={"client_message_id": str(uuid.uuid4()), "content": "reconnect probe"},
        headers={**HEADERS, "Idempotency-Key": str(uuid.uuid4())},
    ) as response:
        async for chunk in response.aiter_bytes():
            for line in chunk.decode("utf-8").splitlines():
                if line:
                    event = json.loads(line)
                    run_id = event.get("run_id")
                    break
            break
    if run_id is None:
        return {"catchup_ms": -1}
    await asyncio.sleep(0.3)
    cursor = 0
    catchup_started = time.perf_counter()
    async with client.stream(
        "POST",
        f"/v1/response-runs/{run_id}/stream",
        json={"after_sequence": cursor},
        headers=HEADERS,
    ) as follower:
        async for _chunk in follower.aiter_bytes():
            pass
    return {"catchup_ms": (time.perf_counter() - catchup_started) * 1000}


def summarized(values: list[float]) -> dict[str, float]:
    clean = [value for value in values if value >= 0]
    if not clean:
        return {"p50": -1, "p95": -1, "max": -1}
    clean.sort()
    p95_index = int(len(clean) * 0.95) - 1
    return {
        "p50": round(statistics.median(clean), 1),
        "p95": round(clean[max(p95_index, 0)], 1),
        "max": round(clean[-1], 1),
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--streams", type=int, default=50)
    parser.add_argument("--create-rate", type=float, default=5.0)
    parser.add_argument("--long-share", type=float, default=0.2)
    parser.add_argument("--cancel-share", type=float, default=0.1)
    args = parser.parse_args()

    process = psutil.Process()
    rss_before = process.memory_info().rss
    pool_errors = 0
    results: list[dict[str, float]] = []

    limits = httpx.Limits(max_connections=100, max_keepalive_connections=100)
    async with httpx.AsyncClient(base_url=API, timeout=httpx.Timeout(120), limits=limits) as client:
        conversations = [await create_conversation(client) for _ in range(args.streams)]

        async def run_one(index: int) -> None:
            nonlocal pool_errors
            cancel_after = None
            if index / args.streams >= 1 - args.cancel_share:
                cancel_after = 0.4
            try:
                results.append(
                    await stream_turn(client, conversations[index], cancel_after=cancel_after)
                )
            except httpx.HTTPError as error:
                pool_errors += 1
                results.append({"error": str(type(error).__name__)})

        interval = 1.0 / args.create_rate
        tasks = []
        for index in range(args.streams):
            tasks.append(asyncio.create_task(run_one(index)))
            await asyncio.sleep(interval)
        await asyncio.gather(*tasks)

        reconnect = await reconnect_probe(client)
        metrics = (await client.get("/metrics")).text
        rss_after = process.memory_info().rss

    def values(key: str) -> list[float]:
        return [item[key] for item in results if key in item]

    mismatch = 0.0
    for line in metrics.splitlines():
        if line.startswith("copilot_content_mismatch_total"):
            mismatch = float(line.rsplit(" ", 1)[1])

    report = {
        "streams": args.streams,
        "create_rate_per_second": args.create_rate,
        "mix": {
            "complete": 1 - args.long_share - args.cancel_share,
            "long": args.long_share,
            "cancel": args.cancel_share,
        },
        "accept_ms": summarized(values("accept_ms")),
        "first_event_ms": summarized(values("first_event_ms")),
        "first_delta_ms": summarized(values("first_delta_ms")),
        "cancel_ack_ms": summarized(values("cancel_ack_ms")),
        "total_ms": summarized(values("total_ms")),
        "reconnect_catchup_ms": reconnect["catchup_ms"],
        "events_total": int(sum(values("events"))),
        "http_errors": pool_errors,
        "content_mismatch_total": mismatch,
        "rss_delta_mb": round((rss_after - rss_before) / (1024 * 1024), 1),
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
