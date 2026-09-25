# Phase 03 — Provider streaming

> Requires Phase 02.

**Goal:** Supervised generation writes committed events from a provider port. FakeProvider is deterministic. xAI adapter exists but is not required for CI.

**Spec:** `docs/LLD.md` provider + supervisor, `docs/configuration.md`, ADR-011, `docs/HLD.md` data flow.

## Files

- Create: `services/api/app/providers/protocol.py`, `fake.py`, `xai.py`
- Create: `services/api/app/chat/supervisor.py`, `context.py`
- Create: `services/api/app/api/responses.py` (create-and-stream headers + follower)
- Test: `services/api/tests/test_fake_provider.py`, `test_supervisor.py`, `test_stream_http.py`

### Task 1: Provider port and FakeProvider

```python
class LlmProvider(Protocol):
    def stream(self, messages: Sequence[ProviderMessage], *, signal: CancelSignal) -> AsyncIterator[ProviderDelta]: ...
```

- [x] Scripted fake: yields `["Back", "pressure"]` then finish `stop` with usage.
- [x] Scripted fail after N deltas with `provider_unavailable`.
- [x] Scripted ignore-cancel until `signal` then stop.
- [x] Scripted hang past idle timeout (the supervisor, not the fake, enforces idle).
- [x] Commit `feat: add provider protocol and fake adapter`.

### Task 2: Context construction

- [x] Newest turns fit `CONTEXT_CHAR_BUDGET`; oldest dropped first.
- [x] Only `is_visible` assistant messages; hidden versions excluded.
- [x] Failed empty assistant messages excluded; visible non-empty cancelled/failed included.
- [x] System prompt from config prepended.
- [x] Telemetry records dropped-turn count, not content.
- [x] Commit `feat: add conversation context windowing`.

### Task 3: Supervisor

- [x] `start(run_id)` **renews** the existing lease (does not insert the first lease), opens provider, `append_delta` on flush thresholds (`DELTA_FLUSH_MS` / `DELTA_FLUSH_CHARS`), heartbeats are **not** written to DB. A timer `≤ LEASE_SECONDS` runs the Phase 02 **periodic** reaper (NULL/expired leases only). Startup still runs the broader this-instance cleanup from Phase 02.
- [x] Observes `cancel_requested_at` and `signal`; commits `response.cancelled`.
- [x] Provider error → `fail_run` with public code, partial kept.
- [x] Output longer than `MAX_OUTPUT_CHARS` → `output_limit_exceeded`.
- [x] Shutdown: stop admission, wait `SHUTDOWN_GRACE_SECONDS`, fail remaining owned runs.
- [x] Commit `feat: supervise in-process generation`.

### Task 4: NDJSON HTTP follower

- [x] `POST /v1/conversations/{id}/responses` returns `application/x-ndjson`, `Cache-Control: no-cache, no-store`, `X-Accel-Buffering: no`.
- [x] Each line is one fixture-valid envelope ending in `\n`.
- [x] Idempotent replay attaches follower from sequence 0.
- [x] `POST /v1/response-runs/{id}/stream` with `after_sequence`.
- [x] `POST .../retry` and `POST .../regenerations` return **200 NDJSON** of the new run (same headers as create-and-stream); require `Idempotency-Key`.
- [x] Test with FakeProvider: collect lines, parse, assert started → deltas → completed.
- [x] Commit `feat: stream committed events as ndjson`.

### Task 5: xAI adapter (CI-optional)

- [x] `XaiProvider` uses `XAI_API_KEY`, `XAI_BASE_URL`, `XAI_MODEL`.
- [x] Maps streamed output text to `ProviderDelta`; drops reasoning/tool payloads.
- [x] Marked `@pytest.mark.live` — not run in default CI.
- [x] Commit `feat: add xai streaming adapter`.

## Stop gate

FakeProvider journeys complete, fail, and cancel deterministically with matching DB terminal events. No content in logs (assert log caplog).
