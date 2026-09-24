# Load rehearsal report (Phase 08)

The harness `services/api/tests/load/load_stream_mix.py` assigns the
`docs/configuration.md` §6 mix (50 streams, 5 creates/s, 70 % complete /
20 % long / 10 % cancel) and records peak in-flight, accept latency,
first NDJSON event, cancel acknowledgement, reconnect time to the first
followed event, HTTP errors, harness-process RSS, and a client-side compare of
streamed vs stored assistant length.

**No production-like soak is attached to this file.** A short FakeProvider
script on a local workstation does not produce 50 in-flight runs, does not
exercise heartbeats/leases/timeouts/retention, and does not sample API RSS or
database pool checkout. Do not treat the numbers below as calibrated defaults.

## What the harness measures

| Field | Meaning |
|---|---|
| `accept_ms` | Client time until the create-response HTTP status |
| `first_event_ms` | Client time until the first NDJSON line (includes provider delay) |
| `first_delta_ms` | Client time until the first `message.delta` |
| `cancel_ack_ms` | Cancel POST until GET run is terminal |
| `reconnect_catchup_ms` | Follow from `after_sequence=last_sequence` until the first byte |
| `peak_in_flight` | Maximum overlapping `run_one` tasks |
| `http_errors` | `httpx.HTTPError` count (not DB pool timeouts) |
| `rss_delta_mb` | Harness process RSS, labeled `rss_source=harness_process` |
| `content_mismatch_total` | Streamed vs stored assistant length (`harness_canonical_compare`) |

## Short-script rehearsal (2026-09-23, not a soak)

Recorded on a local workstation with a ~20-delta / 20 ms FakeProvider plan.
Peak in-flight was a handful of runs. Mix assignment was not applied on that
day. Kept only as a smoke of the harness wiring:

| Measurement | p50 | p95 | max |
|---|---:|---:|---:|
| Accept latency | 10.6 ms | 16.5 ms | 30.5 ms |
| First NDJSON event | 64.6 ms | 71.2 ms | 88.3 ms |
| First delta visible | 65.3 ms | 79.4 ms | 141.4 ms |
| Cancel request → terminal | 6.9 ms | 7.1 ms | 8.6 ms |
| Generation duration (short script) | 536.5 ms | 548.4 ms | 558.8 ms |

## How to run a real mix

```sh
FAKE_PROVIDER_PLAN='[{"deltas": ["token "] * 20, "delay_seconds": 0.2}]' \
FAKE_PROVIDER_LONG_DELAY_SECONDS=1.5 \
CREATE_RESPONSE_PER_MINUTE=1000 \
MAX_ACTIVE_RUNS_PER_USER=100 \
uv run --project services/api uvicorn app.main:create_app --factory \
  --app-dir services/api --host 127.0.0.1 --port 8000
uv run --project services/api python services/api/tests/load/load_stream_mix.py
```

Attach the JSON report here only after `peak_in_flight` approaches 50 and the
run includes the long-share delay. Until then §7 values stay uncalibrated.
