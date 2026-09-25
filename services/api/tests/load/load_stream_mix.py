"""Load rehearsal: the configuration.md §6 mix against the local fake provider.

A 50-in-flight mix from one user needs the per-user cap raised for the run
(`MAX_ACTIVE_RUNS_PER_USER=100`) and a long-stream delay on marked prompts:

    FAKE_PROVIDER_PLAN='[{"deltas": ["token "] * 20, "delay_seconds": 0.2}]' \
    FAKE_PROVIDER_LONG_DELAY_SECONDS=1.5 \
    CREATE_RESPONSE_PER_MINUTE=1000 \
    MAX_ACTIVE_RUNS_PER_USER=100 \
    uv run --project services/api uvicorn app.main:create_app --factory \
        --app-dir services/api --host 127.0.0.1 --port 8000

then:

    uv run --project services/api python services/api/tests/load/load_stream_mix.py

Long kinds send `load rehearsal [long]` so FakeProvider applies
`FAKE_PROVIDER_LONG_DELAY_SECONDS`. This is a rehearsal harness: RSS is the
harness process, HTTP errors are not DB pool timeouts, and peak_in_flight is
what the scheduler actually produced.
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
    client: httpx.AsyncClient,
    conversation_id: str,
    *,
    content: str,
    cancel_after: float | None,
) -> dict[str, float]:
    started = time.perf_counter()
    accept_at: float | None = None
    first_event_at: float | None = None
    first_delta_at: float | None = None
    cancel_ack_at: float | None = None
    run_id: str | None = None
    events = 0
    streamed = ""

    async with client.stream(
        "POST",
        f"/v1/conversations/{conversation_id}/responses",
        json={"client_message_id": str(uuid.uuid4()), "content": content},
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
                if event["type"] == "message.delta":
                    streamed += str(event.get("data", {}).get("delta") or "")
                    if first_delta_at is None:
                        first_delta_at = now
                if event["type"] == "message.completed":
                    streamed = str(event.get("data", {}).get("content") or streamed)
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
        "streamed_content_len": float(len(streamed)),
    }


def assign_kind(index: int, streams: int, long_share: float, cancel_share: float) -> str:
    """70/20/10 by default: complete / long / cancel."""
    cancel_n = int(round(streams * cancel_share))
    long_n = int(round(streams * long_share))
    if index < cancel_n:
        return "cancel"
    if index < cancel_n + long_n:
        return "long"
    return "complete"


async def reconnect_probe(client: httpx.AsyncClient) -> dict[str, float]:
    conversation_id = await create_conversation(client)
    run_id: str | None = None
    last_sequence = 0
    async with client.stream(
        "POST",
        f"/v1/conversations/{conversation_id}/responses",
        json={"client_message_id": str(uuid.uuid4()), "content": "reconnect probe"},
        headers={**HEADERS, "Idempotency-Key": str(uuid.uuid4())},
    ) as response:
        async for chunk in response.aiter_bytes():
            for line in chunk.decode("utf-8").splitlines():
                if not line:
                    continue
                event = json.loads(line)
                run_id = str(event.get("run_id") or run_id)
                last_sequence = int(event.get("sequence") or last_sequence)
                if last_sequence >= 1:
                    break
            if last_sequence >= 1:
                break
    if run_id is None:
        return {"catchup_ms": -1, "after_sequence": 0}
    await asyncio.sleep(0.3)
    catchup_started = time.perf_counter()
    async with client.stream(
        "POST",
        f"/v1/response-runs/{run_id}/stream",
        json={"after_sequence": last_sequence},
        headers=HEADERS,
    ) as follower:
        async for chunk in follower.aiter_bytes():
            if chunk:
                break
    return {
        "catchup_ms": (time.perf_counter() - catchup_started) * 1000,
        "after_sequence": last_sequence,
    }


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
    content_mismatches = 0
    in_flight = 0
    peak_in_flight = 0
    results: list[dict[str, float]] = []
    kinds = [
        assign_kind(index, args.streams, args.long_share, args.cancel_share)
        for index in range(args.streams)
    ]

    limits = httpx.Limits(max_connections=100, max_keepalive_connections=100)
    async with httpx.AsyncClient(base_url=API, timeout=httpx.Timeout(120), limits=limits) as client:
        conversations = [await create_conversation(client) for _ in range(args.streams)]

        async def run_one(index: int) -> None:
            nonlocal pool_errors, content_mismatches, in_flight, peak_in_flight
            kind = kinds[index]
            cancel_after = 0.4 if kind == "cancel" else None
            prompt = "load rehearsal [long]" if kind == "long" else "load rehearsal"
            in_flight += 1
            peak_in_flight = max(peak_in_flight, in_flight)
            try:
                outcome = await stream_turn(
                    client,
                    conversations[index],
                    content=prompt,
                    cancel_after=cancel_after,
                )
                outcome["kind"] = 1.0 if kind == "long" else 0.0
                if kind != "cancel":
                    snapshot = (
                        await client.get(
                            f"/v1/conversations/{conversations[index]}",
                            headers=HEADERS,
                        )
                    ).json()
                    assistants = [
                        item["content"]
                        for item in snapshot["messages"]["items"]
                        if item["role"] == "assistant"
                    ]
                    canonical = assistants[-1] if assistants else ""
                    streamed_len = int(outcome.get("streamed_content_len") or 0)
                    if len(canonical) != streamed_len:
                        content_mismatches += 1
                results.append(outcome)
            except httpx.HTTPError as error:
                pool_errors += 1
                results.append({"error": str(type(error).__name__)})
            finally:
                in_flight -= 1

        interval = 1.0 / args.create_rate
        tasks = []
        for index in range(args.streams):
            tasks.append(asyncio.create_task(run_one(index)))
            await asyncio.sleep(interval)
        await asyncio.gather(*tasks)

        reconnect = await reconnect_probe(client)
        rss_after = process.memory_info().rss

    def values(key: str) -> list[float]:
        return [item[key] for item in results if key in item]

    report = {
        "streams": args.streams,
        "create_rate_per_second": args.create_rate,
        "peak_in_flight": peak_in_flight,
        "rss_source": "harness_process",
        "mix": {
            "complete": kinds.count("complete"),
            "long": kinds.count("long"),
            "cancel": kinds.count("cancel"),
        },
        "reconnect_after_sequence": reconnect.get("after_sequence", 0),
        "accept_ms": summarized(values("accept_ms")),
        "first_event_ms": summarized(values("first_event_ms")),
        "first_delta_ms": summarized(values("first_delta_ms")),
        "cancel_ack_ms": summarized(values("cancel_ack_ms")),
        "total_ms": summarized(values("total_ms")),
        "reconnect_catchup_ms": reconnect["catchup_ms"],
        "events_total": int(sum(values("events"))),
        "http_errors": pool_errors,
        "content_mismatch_total": content_mismatches,
        "content_mismatch_source": "harness_canonical_compare",
        "rss_delta_mb": round((rss_after - rss_before) / (1024 * 1024), 1),
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
