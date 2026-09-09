# Resilience, Retry, Cancellation, and Reconciliation

## 1. Failure model

The design treats four truths separately:

1. What the user currently sees.
2. What the browser has received.
3. What the server has committed.
4. Whether provider generation is still running.

Only server-committed state is canonical. The UI may be ahead optimistically or behind because of buffering/disconnection, but reconciliation always converges to canonical state.

## 2. Optimistic send

Before network I/O, the client creates a `client_message_id`, an idempotency key, an optimistic user message, and an assistant placeholder. The same logical send keeps both IDs across transport retries.

On `response.started`, the reducer maps the optimistic user message to `user_message_id`, assigns `assistant_message_id` and `run_id`, and preserves display order. If the request is rejected before persistence, the user message remains editable/retryable and is marked unsent. If the outcome is unknown, it is marked reconciling—not failed—until history or idempotent replay resolves it.

## 3. Reconciliation algorithm

1. Fetch the canonical conversation and any known run.
2. Match user messages by canonical ID, then `client_message_id`.
3. Replace canonical message fields; retain only unsent optimistic drafts absent from the server.
4. For each run, compare terminal status and `last_sequence`.
5. If active and the client cursor is behind, follow from `last_sequence_applied`.
6. If terminal, replace partial assistant text with canonical content and terminal metadata.
7. If the server has no resource for an ambiguous optimistic send, retry once with the original idempotency key; only then show unsent.

## 4. Retry taxonomy

### Automatic

- Read-only history/status requests: exponential backoff with jitter and a small bounded attempt count.
- Stream follow after a transient disconnect: resume from the last applied sequence while the run is active.
- Original create request with unknown outcome: repeat with the same idempotency key.

### User-driven

- Provider/server terminal failure: “Retry” creates a new run for the same user message.
- Completed answer: “Regenerate” creates a new answer version and supersedes the visible prior answer only after the new run is accepted.
- Validation/auth/ownership failure: no blind retry; show the required corrective action.

No automatic retry creates new assistant generation after a terminal provider failure because that could spend money without user intent.

## 5. Cancellation

`AbortController.abort()` only stops the browser read. It does not prove provider cancellation. The client therefore sends an idempotent cancel request using a different controller and shows `stopping` until canonical state arrives.

Race outcomes:

- Cancel wins: partial content is committed and the run becomes `cancelled`.
- Completion wins: cancel returns the already-completed snapshot and the UI shows the complete answer.
- Cancel request outcome is unknown: client reconciles status and never assumes cancellation.
- Provider ignores close: server enforces an overall deadline and records cancellation latency/failure.

## 6. Reconnect

The browser reconnects when online, visible, and the run is known active. It sends `after_sequence` and accepts duplicate delivery. A bounded backoff prevents reconnect storms. Navigation away does not cancel generation; returning to the conversation follows the active run.

If replay retention no longer contains the cursor, the server emits a canonical snapshot. If the server process died, orphan recovery marks the run `failed/server_restart`; the client retains partial content and offers retry.

## 7. Graceful degradation

| Condition | User experience | Server behavior |
|---|---|---|
| Provider unavailable | History works; send shows retryable failure | Fast failure/circuit telemetry; no message loss |
| Database unavailable | Read/send unavailable with clear service error | Readiness fails; no generation begins without durable run |
| Stream blocked/buffered by proxy | Connecting timeout, then reconcile | Heartbeat and buffering headers aid diagnosis |
| Browser lacks stream APIs | Non-streaming mode waits for terminal canonical response | Same run lifecycle, periodic status read |
| Offline during send | Optimistic message remains unsent | No request assumed committed |
| Offline during stream | Partial stays visible and marked reconnecting | Generation continues on owning process |
| Malformed event/gap | Stop applying deltas; reconcile | Diagnostic correlates run and sequence |
| Rate limited | Existing history remains usable; retry hint shown | Stable 429 problem response |

## 8. Timeouts

Distinct configurable deadlines exist for request validation/transaction, provider connect, provider idle, total generation, stream heartbeat, and graceful shutdown. A timeout produces a stable failure code and preserves committed partial content. Concrete values are calibrated under Phase 08 tests rather than guessed in architecture.

## 9. Duplicate and ordering defense

- Ignore events at or below the applied sequence.
- On a gap, do not apply later content; reconnect from the known cursor.
- Check `content_index` before appending a delta.
- Replace accumulated output with `message.completed.content`.
- The database serializes event sequence allocation per run.
