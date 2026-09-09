# Architecture Decisions

## ADR-001: Full chat product boundary

**Decision:** Persist conversations and support send, cancel, retry, regenerate, restore, and history—not a single prompt demo.

**Reason:** These lifecycle edges are the actual subject of the project.

## ADR-002: POST with Fetch streaming

**Decision:** Use `fetch()` and `ReadableStream` for browser streaming.

**Alternatives:** Browser `EventSource` is GET-oriented; WebSockets add bidirectional connection machinery not required by V1.

## ADR-003: Typed NDJSON

**Decision:** Emit one versioned JSON event per newline using `application/x-ndjson`.

**Alternatives:** Raw text cannot carry IDs, status, usage, or structured failure; SSE framing is unnecessary when Fetch already exposes the response body.

## ADR-004: Modular monolith

**Decision:** One Next.js app, one FastAPI service, and PostgreSQL.

**Alternatives:** Microservices and a dedicated orchestration platform create more deployment and failure modes without a V1 need.

## ADR-005: Durable event replay in PostgreSQL

**Decision:** Persist per-run sequenced events and stream committed rows. Supervise provider generation independently of the browser connection inside the API process.

**Alternatives:** Request-owned streaming loses reconnectability; Redis/queue infrastructure is deferred until measured scale or restart-survival requirements justify it.

**Known ceiling:** An API crash ends supervised generation. Recovery marks the run failed and safe retry creates a replacement.

## ADR-006: Linear conversation with answer versions

**Decision:** One active response per conversation. Regeneration creates a new response run for the same user message and supersedes the previous visible assistant answer.

**Alternatives:** Full conversation branching is a separate product and data-model commitment.

## ADR-007: Idempotency at the database boundary

**Decision:** Scope `Idempotency-Key` to user plus operation and enforce it with a unique constraint. A replay returns the existing run and stream.

**Reason:** Network ambiguity must never duplicate a turn.

## ADR-008: Authentication supplied by host product

**Decision:** Define an authenticated-principal interface and local development identity. Do not build an identity provider.

**Reason:** Authentication product work is orthogonal; authorization remains mandatory at every conversation query.

## ADR-009: Contract-first without code generation in V1

**Decision:** Pydantic models define server events; checked-in JSON fixtures exercise the browser union/parser, and schema snapshots detect drift.

**Alternatives:** A code-generation toolchain removes some duplication but adds build complexity before the contract is stable.

## ADR-010: Provider-neutral core

**Decision:** One small provider port normalizes text deltas, finish reason, usage, and provider error. Implement one provider first.

**Alternatives:** A plugin registry or provider factory is speculative until a second provider exists.

## ADR-011: xAI is the V1 production provider

**Decision:** The single production adapter calls xAI (`XAI_API_KEY`, `https://api.x.ai/v1`, default model `grok-4.6`) through the OpenAI-compatible Responses API with streaming. Tests and keyless local development use `FakeProvider`.

**Reason:** One real provider is enough to prove the port. Tools, search, and images stay disabled so model output remains inert data.

## ADR-012: Connection-only heartbeats; synthesized snapshots

**Decision:** `heartbeat` is not stored and does not consume sequence. `response.snapshot` is synthesized on replay when history is compacted or the cursor is below retention; it is not an append-only event row.

**Reason:** Replay must reconstruct chat state, not idle keepalives. Clients that ignore unknown types would drop snapshots if they were unspecified.

## ADR-013: Generation owner lease

**Decision:** `response_runs.owner_instance_id` plus `lease_expires_at` identify the supervising API process. Every replica reaps NULL or expired leases on a timer (not only at boot). Cancel is a cross-replica column; the owner observes it. Live processes must use distinct instance ids.

**Reason:** Without a lease, replica restart would fail live runs owned by healthy replicas.

## ADR-014: Dual auth adapters, one Actor

**Decision:** Production validates host JWT (JWKS) from `Authorization: Bearer`. Optional cookie mode (`AUTH_COOKIE_NAME`) stores the **same JWT**, `HttpOnly; Secure; SameSite=Lax`, with double-submit `X-CSRF-Token` / `csrf_token` and Origin allow-list. Development uses `X-Dev-User` / `DEV_USER_ID` and cannot be enabled outside `APP_ENV=development`.

**Reason:** The host product supplies identity; this service only binds `user_id` onto every query.

## ADR-015: Retry and regenerate share persistence, not eligibility

**Decision:** Both create a new assistant version and run because terminal message content is immutable. Eligibility differs: retry is for `failed`/`cancelled`; regenerate is the user control for a new answer and is blocked while a run is active.

## ADR-016: No feature flags and no OpenAPI codegen

**Decision:** V1 ships configuration, not flags. HTTP OpenAPI is a checked-in snapshot for drift detection (`contracts/openapi.yaml`); it is not used to generate clients. Event contracts remain JSON Schema + fixtures (ADR-009).
