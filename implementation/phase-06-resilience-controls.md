# Phase 06 — Resilience and lifecycle controls

> Requires Phase 05.

**Goal:** Cancel, retry, regenerate, reconnect, and degradation journeys work in a browser and match canonical DB state.

**Spec:** `docs/resilience-and-reconciliation.md`, `docs/state-machine.md`, production scenarios 4–7, PRD acceptance steps 5–7.

## Files

- Create: `apps/web/features/chat/state/recovery.ts`
- Modify: Composer/Stop, per-message Retry/Regenerate
- Test: reducer races; Playwright `cancel.spec.ts`, `reconnect.spec.ts`, `retry.spec.ts`, `ambiguous-send.spec.ts`

### Task 1: Canonical cancel

- [ ] Stop: `AbortController.abort()` on the stream **and** `POST /cancel` with a new controller (no idempotency key).
- [ ] UI shows `stopping` until canonical `cancelled` or `completed`.
- [ ] Reducer: `stopping → completed` when completion wins.
- [ ] Cancel of terminal run is success no-op.
- [ ] Playwright: stop mid-stream; DB run `cancelled`; partial text visible and labeled stopped.
- [ ] Commit `feat: cancel local stream and canonical run`.

### Task 2: Reconnect from cursor

- [ ] On disconnect, recovery coordinator `GET` run; if active, `followResponse(runId, lastSequence)`.
- [ ] Duplicates ignored; gaps trigger snapshot/follow, never guessed text.
- [ ] Navigation away does not cancel; returning follows the active run.
- [ ] Playwright: kill the follower (API test hook or offline) then restore; final text matches DB; no duplicated paragraphs.
- [ ] Commit `feat: resume streams from event cursor`.

### Task 3: Ambiguous create

- [ ] Fetch failure with no HTTP status: keep reconciling, retry **once** with same idempotency key and `client_message_id`.
- [ ] If server has the row, attach stream; if 409 busy, follow `active_run_id`.
- [ ] Playwright or integration: drop the response after commit; client retry does not create a second user message.
- [ ] Commit `feat: reconcile ambiguous sends with idempotency`.

### Task 4: Retry and regenerate UI

- [ ] Failed/cancelled: Retry enabled; calls `POST .../retry` with new key, streams the new run.
- [ ] Completed: Regenerate enabled; previous answer not shown as the live bubble (`is_visible`).
- [ ] No automatic retry after terminal provider failure.
- [ ] Playwright both paths; assert one user message, two runs in DB for regenerate.
- [ ] Commit `feat: retry and regenerate without duplicating user turns`.

### Task 5: Degradation

- [ ] Provider down: history usable; send shows retryable error.
- [ ] Rate limit 429 shows retry hint, does not spam.
- [ ] Missing ReadableStream: poll `GET` run until terminal (feature-detect).
- [ ] Commit `feat: degrade chat when generation is unavailable`.

## Stop gate

Failure-injection browser journeys pass. Cancel/complete race cannot display cancelled over a completed canonical answer.
