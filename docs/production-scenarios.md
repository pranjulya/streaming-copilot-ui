# Production Scenarios and Runbooks

## 1. Provider latency spike

**Signal:** Provider first-token latency rises while API acceptance and database latency remain healthy.

**Behavior:** Existing history works; connecting state remains explicit; connect/idle deadlines prevent hanging streams.

**Response:** Segment by provider/model, reduce admission if needed, show retryable errors, and avoid blind retries that multiply load.

## 2. Provider returns 429 or 5xx mid-stream

Persist partial content, commit `response.failed` with a stable retryable code, and expose user-driven retry. Do not leak provider response bodies.

## 3. Database unavailable

Readiness fails and new runs do not start because no canonical record can be created. Already-running provider tasks stop safely when they cannot commit within the bounded persistence policy; no unpersisted final answer is claimed complete.

## 4. API replica termination

The replica stops admission, drains active tasks for the grace period, and closes followers. Runs that do not reach terminal state are recovered as `failed/server_restart`; other replicas can serve history and safe retry.

## 5. Network loss during generation

The client retains partial content and cursor, then reconnects and replays. Generation continues on its owning replica. Duplicate events are ignored by sequence.

## 6. Cancel races with completion

Whichever terminal transaction commits first wins. Cancel on an already terminal run is a no-op. The browser reconciles rather than overwriting completed state with a local cancelled assumption.

## 7. Duplicate submit or browser retry

Same idempotency key and request hash returns the existing run; a changed hash returns conflict. Database uniqueness prevents duplicate canonical user messages under concurrency.

## 8. Slow consumer

HTTP sending applies backpressure to that follower while generation writes bounded events independently. If the follower exceeds idle/connection policy, close it; the client can replay later. Monitor event backlog and connection memory.

## 9. Proxy buffers chunks

Symptoms are high service-to-render latency despite healthy provider/event commits. Verify compression and buffering settings, NDJSON content type, heartbeat visibility, and CDN route behavior. Fall back to terminal polling only as a degraded client mode.

## 10. Event table growth

Track rows/bytes per run and age. Compact terminal runs after the configured replay window, retaining canonical message/run state. Active-run events are never compacted. Verify snapshot fallback before enabling deletion.

## 11. Bad deployment or migration

Use backward-compatible expand/contract migrations. Deploy schema before readers/writers that need it. Roll back application first; destructive contract steps require a later release after all old code is gone. Restore rehearsal verifies backups independently.

## 12. Suspected data exposure

Revoke affected credentials, restrict traffic, preserve protected audit evidence, identify resources through IDs rather than content logs, follow incident policy, and validate deletion/notification obligations. Do not increase content logging during the incident.

## 13. Cost anomaly

Compare accepted runs, output token distribution, retries, cancellation, user/network signals, and model dimension. Apply existing per-user/run limits before global shutdown; preserve history access.

## 14. Model quality regression

Freeze rollout, compare the versioned evaluation set and prompt/model identifiers, restore the last accepted configuration, and keep transport rollout separate from model/prompt changes where possible.

## Runbook template

Each scenario above is executed with this operator checklist (Phase 07 fills dashboard links):

1. **Detect** — named metric/alert from `docs/observability.md`.
2. **Confirm** — distinguish provider vs API vs database vs proxy using accept latency, first-token latency, and readiness.
3. **Mitigate** — preserve history access; fail new runs cleanly; do not enable content logging.
4. **Recover** — restore config/model/replica; users retry failed runs.
5. **Evidence** — diagnostic IDs, not prompt text; attach to the incident record.
