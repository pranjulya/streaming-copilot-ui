# Questions and Answers

## Why NDJSON instead of raw chunks?

Raw text cannot reliably communicate canonical IDs, lifecycle states, usage, typed errors, or future tool/citation status. NDJSON retains ordinary HTTP streaming while adding a small, inspectable envelope.

## Why not use `EventSource`?

The browser API is designed around GET. Chat creation naturally needs a POST body and cancellation signal, so Fetch streaming avoids an extra create-then-subscribe protocol.

## Why not WebSockets?

V1 has one client request producing one server stream. It does not need presence, peer collaboration, or many unsolicited server channels. WebSockets would add connection/auth/reconnect infrastructure without solving a current requirement.

## Can a network chunk equal an event?

No. A chunk can contain part of an event, several events, or split a UTF-8 character. Only newline framing after streaming text decode determines event boundaries.

## Why include both `sequence` and `event_id`?

`sequence` orders and resumes one run. `event_id` gives globally unique correlation and diagnostic deduplication.

## Why replace text on `message.completed`?

The final database content is canonical. Replacement corrects missed, duplicated, normalized, or otherwise divergent deltas.

## Does `AbortController` cancel the model?

It cancels the local request/read. The client must also call the server cancel endpoint. Only the canonical run state confirms that provider work ended.

## Why persist stream events?

They make browser reconnect deterministic: replay after a sequence, deduplicate, and catch up. Without them, the system can persist only snapshots and cannot reproduce missed typed lifecycle events.

## Why keep generation in an API process?

It is the smallest V1 design that allows browser disconnect/replay while avoiding a queue and worker service. The documented ceiling is process loss: orphan recovery fails the run and offers safe retry.

## Why not add Redis now?

PostgreSQL already owns canonical state and provides adequate V1 replay semantics. Redis becomes justified when measurements show database pressure, cancellation latency, or restart-survival needs.

## What prevents duplicate user messages?

A stable client message UUID, an idempotency record scoped to user/operation, request-hash validation, and database uniqueness. Client state alone is not sufficient under concurrent retries.

## What is retry versus regenerate?

Retry follows a failed or cancelled run for the same user message. Regenerate asks for a new answer version even when a prior answer completed. Both create new immutable response runs.

## Why only one active run per conversation?

It keeps context order and controls understandable. The database enforces it, avoiding two overlapping answers racing to become the next turn.

## How does refresh recovery work?

The browser loads canonical history and run state. If a run is active, it follows events after its last known sequence; if terminal, it replaces local partial state with the server snapshot.

## What if the server crashes mid-generation?

No uncommitted text is claimed. Startup recovery marks the orphan run failed with a safe code, retains committed partial content, and lets the user retry.

## Why are tools reserved but not implemented?

Typed events should evolve compatibly, but a tool framework brings authorization and execution risks that the V1 product does not require.

## How is prompt injection handled?

V1 gives model text no authority: there are no tools, secrets in context, or executable output. Output is sanitized. Future tools require their own least-privilege authorization and confirmation model.

## Why test with a fake provider?

It produces exact chunks, timing, failures, and cancellation behavior deterministically. Real-model evaluations remain useful but should not make transport CI flaky or expensive.

## Why a generation lease?

Multiple API replicas can serve history, replay, and cancel. Only the process with a live `owner_instance_id` lease generates. Startup recovery must not fail another replica’s live run.

## Why are retry and regenerate the same write?

Terminal assistant content is immutable. Both operations hide the previous visible answer and insert a new assistant message plus run. The product difference is which button is offered, not the tables written.

## Which model does V1 call?

xAI `grok-4.6` through the streaming Responses API. The application protocol stays provider-neutral; tests use `FakeProvider`.

## What is the most important invariant?

The database run/message state and emitted terminal event agree. The browser can always recover if that invariant holds.
