# Learning Path

This path follows the implementation phases but is useful before code begins. Each step has an observable result and a question to answer before moving on.

## 1. Frame the product lifecycle

Read `docs/PRD.md`, `docs/state-machine.md`, and `docs/resilience-and-reconciliation.md`.

Learn why a chat product is not merely “render tokens”: user intent, canonical persistence, connection lifetime, and provider generation lifetime can diverge.

Checkpoint: explain why aborting a browser fetch does not prove that server generation stopped.

## 2. Understand byte streaming

Read `docs/api-and-stream-contracts.md` and the stream-parser portion of `docs/LLD.md`.

Learn chunk boundaries, streaming UTF-8 decoding, carry buffers, newline framing, backpressure, abort signals, and terminal events.

Checkpoint: describe how one JSON record can arrive across three chunks with a multibyte character split between chunks.

## 3. Model durable chat state

Read `docs/persistence-model.md`.

Learn idempotency, database-enforced concurrency, response attempts, partial content, event sequence allocation, and answer versioning.

Checkpoint: trace the transaction that prevents a double-click from creating two user messages.

## 4. Separate generation from delivery

Read `docs/HLD.md` and the send/replay diagrams.

Learn why the provider task commits durable events while one or more HTTP followers read those events. Compare request-owned generation with durable queue workers.

Checkpoint: state exactly what survives a browser disconnect, an API follower disconnect, and an API process crash.

## 5. Build deterministic client state

Read the reducer interfaces and state diagrams.

Learn optimistic UI, canonical reconciliation, duplicate/gap handling, final-content replacement, and state per run rather than global loading state.

Checkpoint: resolve a cancel/completion race without trusting event arrival order at the browser.

## 6. Design failures before happy paths

Read `docs/production-scenarios.md`.

Learn stable error codes, pre-stream problem details, post-header failure events, reconnect cursors, orphan recovery, and graceful degradation.

Checkpoint: explain why terminal provider failures use user-driven rather than automatic generation retry.

## 7. Secure the boundaries

Read `docs/security.md`.

Learn authentication versus authorization, ownership-scoped queries, CSRF/CORS, Markdown XSS, secrets, rate limits, output bounds, and prompt-injection blast radius.

Checkpoint: list every place a guessed conversation ID must be rejected without revealing whether it exists.

## 8. Observe user experience end to end

Read `docs/observability.md`.

Learn correlation, high-cardinality IDs, metrics versus logs, content privacy, long-lived traces, and service versus provider latency.

Checkpoint: use metrics to distinguish provider slowness from proxy buffering.

## 9. Verify behavior and quality separately

Read `docs/testing-and-evaluation.md`.

Learn deterministic transport tests, real PostgreSQL integration, failure injection, load/backpressure tests, accessibility, and non-deterministic LLM evaluation.

Checkpoint: explain why exact answer text is a poor CI assertion but exact stream ordering is a good one.

## 10. Review before building

Read `Implementation.md`, `docs/configuration.md`, `docs/traceability.md`, `docs/glossary.md`, and every `implementation/phase-0*.md` file. Confirm that each phase has prerequisites, concrete outputs, tests, and a stop gate. Record explicit approval before Phase 00.
