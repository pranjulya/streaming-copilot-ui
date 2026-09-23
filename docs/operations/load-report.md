# Load rehearsal report (Phase 08)

Recorded 2026-09-23 on the local workstation (Apple Silicon, Homebrew PostgreSQL 16
on port 5433, FastAPI via uvicorn, `FakeProvider` with a 20-delta/20 ms script) by
running `services/api/tests/load/load_stream_mix.py` with the `docs/configuration.md`
§6 shape: **50 concurrent streams, 5 creates/s, 70 % short / 20 % long / 10 % cancel**.

`CREATE_RESPONSE_PER_MINUTE` was raised to 1000 for the rehearsal so the per-user
admission limit would not dominate the run (the production default of 20/min is a
deliberate product limit, not a capacity limit).

## Results

| Measurement | p50 | p95 | max |
|---|---:|---:|---:|
| Accept latency | 10.6 ms | 16.5 ms | 30.5 ms |
| Service first event (excludes provider) | 64.6 ms | 71.2 ms | 88.3 ms |
| First delta visible | 65.3 ms | 79.4 ms | 141.4 ms |
| Cancel request → terminal | 6.9 ms | 7.1 ms | 8.6 ms |
| Generation duration (short script) | 536.5 ms | 548.4 ms | 558.8 ms |

Additional observations:

- Reconnect catch-up (follow from sequence 0 for a mid-flight run): **169.9 ms**.
- Events persisted during the run: **486**; HTTP errors: **0**; DB pool timeouts: **0**.
- `copilot_content_mismatch_total` = **0** (streamed terminal content matched storage).
- Process RSS delta across the run: **7.6 MB**.
- A slow reader cannot unbounded-buffer events: followers re-read committed rows with
  bounded polling, and `EVENT_RETENTION_HOURS` (24 h default) bounds row growth.

## Interpretation

- The 50–100 ms first-event floor is the follower's `EVENT_FOLLOW_POLL_MS=50` plus a
  commit; it is well inside the PRD's conversational feel.
- Cancellation acknowledgement is single-digit milliseconds because the supervisor
  polls `cancel_requested_at` on every loop turn.
- These numbers validate the shipped local defaults (see `docs/configuration.md`
  §7 "Calibrated defaults"). Re-run this harness on production-like hardware before
  changing any timeout or flush value.

## How to reproduce

```sh
FAKE_PROVIDER_PLAN='[{"deltas": ["token "], "delay_seconds": 0.0},
  {"deltas": ["t1 ","t2 ","t3 ","t4 ","t5 ","t6 ","t7 ","t8 ","t9 ","t10 ",
              "t11 ","t12 ","t13 ","t14 ","t15 ","t16 ","t17 ","t18 ","t19 ","t20 "],
   "delay_seconds": 0.02}]' \
CREATE_RESPONSE_PER_MINUTE=1000 \
uv run --project services/api uvicorn app.main:create_app --factory \
  --app-dir services/api --host 127.0.0.1 --port 8000
uv run --project services/api python services/api/tests/load/load_stream_mix.py
```
