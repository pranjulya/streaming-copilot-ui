# Phase 02 — Response lifecycle and event store

> Requires Phase 01. No provider I/O in this phase — tests drive the event writer and state machine directly.

**Goal:** Durable response runs, sequenced events, one-active-run, retry/regenerate writes, replay from cursor, and orphan-lease recovery.

**Spec:** `docs/state-machine.md`, `docs/persistence-model.md`, `docs/api-and-stream-contracts.md` events and run endpoints (non-streaming parts).

## Files

- Modify: Alembic new revision for `response_runs` (including lease columns), `stream_events`, `idempotency_records` if not present
- Create: `services/api/app/persistence/runs.py`, `events.py`
- Create: `services/api/app/chat/responses.py`, `state_machine.py`
- Create: `services/api/app/chat/event_writer.py`
- Test: `services/api/tests/test_run_state.py`, `test_event_replay.py`, `test_retry_regenerate.py`

### Task 1: Run + event schema

- [ ] Partial unique index: one non-terminal run per `conversation_id`.
- [ ] Primary key `(run_id, sequence)` on `stream_events`.
- [ ] Migration + model tests. Commit `feat: add response run and stream event tables`.

### Task 2: State machine and event writer

**Produces:**

```python
async def start_run(run_id: UUID) -> StreamEvent
async def append_delta(run_id: UUID, delta: str) -> StreamEvent
async def append_usage(run_id: UUID, usage: Usage) -> StreamEvent
async def complete_run(run_id: UUID, result: CompletionResult) -> tuple[StreamEvent, StreamEvent]
async def fail_run(run_id: UUID, failure: SafeFailure) -> StreamEvent
async def cancel_run(run_id: UUID) -> StreamEvent
async def follow_events(run_id: UUID, after_sequence: int) -> list[StreamEvent]
```

- [ ] **Step 1:** Tests:
  - Illegal transition `completed → streaming` raises.
  - `start_run` is sequence 1 (`response.started`); deltas follow as 2,3; no gaps under concurrency (two writers: one must lose the lock).
  - `append_usage` does not change message content.
  - Terminal methods are idempotent (second `complete_run` returns the same events, no extra rows).
  - `message.completed` content equals messages.content.
  - Cancel from `queued` and `streaming` lands `cancelled` with partial retained; no `message.completed` row.
- [ ] **Step 2:** Implement writer that locks the run row in one transaction with message/run updates.
- [ ] **Step 3:** Commit `feat: add transactional event writer and run state machine`.

### Task 3: Create / retry / regenerate persistence

- [ ] Create-turn transaction: advisory lock on `user_id`, lock conversation, ownership, no active run, per-user cap, insert user message by `client_message_id`, insert assistant placeholder, insert queued run **with lease columns set**, store idempotency, retitle from first user message when title is still `New conversation`.
- [ ] Second create with same key returns existing run; different hash 409.
- [ ] Second create with new key while active → 409 `conversation_busy`.
- [ ] Fourth concurrent run for the same user when cap is 3 → 409 `too_many_active_runs`.
- [ ] Retry from `failed` hides old assistant, inserts version N+1 **with lease columns**, under the same advisory lock and cap as create-turn.
- [ ] Fourth concurrent retry when cap is 3 → 409 `too_many_active_runs`.
- [ ] Retry/regenerate on archived conversation → 409 `conversation_archived`.
- [ ] Retry from `completed` → 409 `invalid_run_state`.
- [ ] Retry from `streaming` → 409 `invalid_run_state`.
- [ ] Regenerate while a run is active → 409 `conversation_busy` with `active_run_id`.
- [ ] Regenerate from `completed` hides old visible answer.
- [ ] Creation failure leaves previous visible (simulate event-writer exception after hide? use a transaction rollback test).
- [ ] Commit `feat: add idempotent create retry and regenerate writes`.

### Task 4: Replay and snapshot synthesis

- [ ] `follow_events(after_sequence=2)` returns events 3+.
- [ ] When events 1–10 deleted and `after_sequence=4`, synthesized `response.snapshot` has `last_sequence` and canonical content (helper may delete rows in test).
- [ ] Commit `feat: add event replay and snapshot fallback`.

### Task 5: Lease orphan recovery

- [ ] Startup reaper fails NULL or expired leases regardless of owner, **and** this-instance non-terminal rows even if the lease is unexpired.
- [ ] Periodic reaper (`≤ LEASE_SECONDS`) fails **only** NULL or expired leases. An unexpired this-instance run the live supervisor is renewing is unchanged.
- [ ] Run with another instance’s **unexpired** lease is unchanged.
- [ ] Fast restart with a new `INSTANCE_ID` before expiry: run stays active until expiry, then the next periodic tick on **any** replica fails it.
- [ ] Fast restart with the **same** `INSTANCE_ID` before expiry: startup reaper fails the this-instance row; a periodic tick would not.
- [ ] Commit `feat: recover expired generation leases`.

### Task 6: Run HTTP (JSON)

- [ ] `GET /v1/response-runs/{id}` ownership 404, returns RunSnapshot.
- [ ] `POST .../cancel` sets `cancel_requested_at`, no idempotency key, terminal cancel is 200 no-op.
- [ ] `GET /v1/conversations/{id}?cursor&limit` oldest-first messages including `is_visible=false`.
- [ ] Commit `feat: add run status and cancel http`.

## Stop gate

Transition, ordering, terminal uniqueness, replay, snapshot, retry/regenerate, and lease tests pass on real PostgreSQL.
