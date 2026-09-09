# Testing and Evaluation Strategy

## 1. Test pyramid

### Unit

- NDJSON parser: split JSON, multiple lines per chunk, split multibyte Unicode, CRLF, final suffix, empty lines, invalid JSON, abort, unsupported major version.
- Reducer: optimistic reconciliation, duplicate/gap handling, final replacement, cancel/complete race, navigation independence.
- Backend state transitions and safe error mapping.
- Context selection, output limits, and ownership-aware repository behavior.

### Contract

- One checked example fixture for every V1 event.
- Backend models serialize fixtures accepted by the frontend parser.
- Envelope invariants, event ordering, terminal uniqueness, and problem detail codes.
- Checked-in `contracts/openapi.yaml` snapshot of HTTP routes reviewed on intentional change (drift test only; no codegen).
- Event JSON Schema at `contracts/stream-events.schema.json` plus one fixture per V1 type including `response.snapshot` and connection-only `heartbeat`.
- Parser tests include CRLF as **tolerance**; the server contract remains LF (`\n`).

### Integration

- FastAPI plus real PostgreSQL for transaction, uniqueness, locks, replay, cancellation, orphan recovery, and pagination.
- Scripted fake provider emits controlled deltas, delays, failures, usage, and ignored cancellation.
- Idempotent duplicate requests create one user message and one run.

### End-to-end

- New conversation → optimistic send → streamed completion → reload.
- Stop during stream and retain canonical partial.
- Disconnect, reconnect from cursor, deduplicate, complete.
- Ambiguous create response reconciles through original idempotency key.
- Retry failure and regenerate completion without duplicating user turn.
- Keyboard, focus, screen-reader status, reduced motion, and mobile layout checks.

## 2. Failure injection

Deterministic scenarios cover provider connect timeout, idle timeout, mid-stream failure, malformed provider chunk, database failure before and after headers, delayed cancellation, API restart, duplicate event delivery, skipped sequence, slow client, proxy buffering symptom, and event-retention snapshot fallback.

Each scenario asserts both browser-visible state and canonical database state.

## 3. Performance

- Measure time to accepted run, first event overhead, first rendered delta, total duration, reconnect catch-up, and cancellation acknowledgement.
- Run concurrent short and long streams against production-like proxy/database settings.
- Verify bounded memory per connection and database pool behavior.
- Test slow readers and confirm generation/event retention remains bounded.
- Determine flush batch, poll, heartbeat, timeout, and retention values from results; record chosen values in configuration documentation before release.

## 4. LLM evaluation

Transport correctness and answer quality are separate gates.

Maintain a small versioned evaluation set containing multi-turn context retention, instruction hierarchy, refusal/safety behavior, Markdown formatting, long-context truncation, and common domain questions. Score:

- Required facts or rubric items
- Unsupported-claim rate on fact-controlled prompts
- Instruction-following and context consistency
- Safety-policy behavior
- Latency and token use

Use deterministic provider fakes for CI. Run real-model evaluations on an explicit scheduled or pre-release job because they cost money and vary over time. Compare candidate changes against a recorded baseline; never gate merges on exact free-form text equality.

## 5. Security and privacy tests

- Cross-user access matrix for conversations, messages, runs, replay, cancel, retry, and regenerate.
- XSS and unsafe-link Markdown corpus.
- Rate/output/body bounds.
- No content or secrets in standard telemetry snapshots.
- Idempotency key reuse with a different request hash returns conflict.

## 6. Release evidence

The release checklist retains CI results, migration rehearsal, load report, evaluation comparison, security scan summary, accessibility report, dashboard screenshots/queries, rollback rehearsal, and named owner approval. No production credentials or user content enter the evidence bundle.
