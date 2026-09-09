# Streaming Copilot UI — Master Implementation Blueprint

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:subagent-driven-development` or `superpowers:executing-plans` only after the complete planning package is approved. Track every phase with its checkboxes and stop at each review gate.

**Goal:** Build a production-minded full-chat Copilot that persists canonical history and streams typed NDJSON responses with deterministic cancellation, retry, regeneration, and recovery.

**Architecture:** A Next.js frontend consumes a FastAPI HTTP stream. FastAPI supervises provider generation, commits canonical messages and sequenced events to PostgreSQL, and streams committed events to connected or reconnecting clients. V1 is a modular monolith with no Redis, worker queue, WebSocket, or tool execution.

**Tech stack:** React 19 / Next.js 15, TypeScript, FastAPI / Python 3.12, PostgreSQL 16, SQLAlchemy/Alembic, native Fetch streams, pytest, Vitest, Playwright, xAI Responses API (`grok-4.6`) plus `FakeProvider`, and vendor-neutral structured telemetry.

**Specifications:** `docs/PRD.md`, `docs/HLD.md`, `docs/LLD.md`, and the remaining documents under `docs/`.

## Global constraints

- Do not begin Phase 00 until the user explicitly approves this planning package.
- Preserve `POST` + Fetch `ReadableStream`, `AbortController`, server-side persistence, and typed NDJSON.
- PostgreSQL is the only required V1 stateful dependency.
- Exactly one active response run per conversation.
- Every mutating retry is idempotent; ownership is enforced in every resource query.
- Model output is sanitized data; no tools, retrieval, attachments, or chain-of-thought in V1.
- Every phase must be independently testable and reviewed before the next phase.
- Add no abstraction for a second provider until a second provider is actually required.

## Planned implementation tree

```text
apps/web/
  app/                         routes and shell
  features/chat/api/           conversation HTTP client
  features/chat/stream/        NDJSON decoding/validation
  features/chat/state/         reducer and recovery coordinator
  features/chat/components/    accessible chat UI
  tests/                       unit/contract/end-to-end support
services/api/
  app/api/                     FastAPI routes/problem mapping
  app/chat/                    conversation/response services and models
  app/persistence/             SQLAlchemy repositories/unit of work
  app/providers/               one provider plus deterministic fake
  app/observability/           correlation/log/metric setup
  tests/                       unit/integration/contract tests
contracts/
  examples/                    canonical event fixtures (one file per V1 type)
  stream-events.schema.json    protocol envelope/event schemas
  openapi.yaml                 HTTP snapshot for drift detection (no codegen)
```

Files appear only when their owning phase begins.

## Phase sequence

| Phase | Deliverable | Independent proof |
|---:|---|---|
| 00 | [Foundation and contracts](implementation/phase-00-foundation-and-contracts.md) | Health checks and contract fixtures pass |
| 01 | [Persistence and conversation API](implementation/phase-01-persistence-and-conversations.md) | Real-DB ownership/idempotency/pagination tests pass |
| 02 | [Response lifecycle and event store](implementation/phase-02-response-lifecycle.md) | Transition, ordering, terminal, and replay tests pass |
| 03 | [Provider streaming](implementation/phase-03-provider-streaming.md) | Scripted provider completes/fails/cancels deterministically |
| 04 | [Frontend chat and history](implementation/phase-04-frontend-chat.md) | UI unit/accessibility checks pass without live generation |
| 05 | [End-to-end typed streaming](implementation/phase-05-end-to-end-streaming.md) | Browser streams split chunks and reloads canonical result |
| 06 | [Resilience and lifecycle controls](implementation/phase-06-resilience-controls.md) | Failure-injection browser journeys pass |
| 07 | [Production guardrails](implementation/phase-07-production-guardrails.md) | Ownership/XSS/telemetry/deploy checks pass |
| 08 | [Verification and release](implementation/phase-08-verification-release.md) | Release checklist and objectives pass |

## Review gates

1. **Planning approval:** required before Phase 00.
2. **Contract gate:** Phase 00 freezes V1 event examples before backend/frontend diverge.
3. **Persistence gate:** Phase 01 proves constraints on real PostgreSQL.
4. **Lifecycle gate:** Phase 03 proves every run reaches a durable terminal state.
5. **Experience gate:** Phase 06 proves lifecycle controls and recovery in a browser.
6. **Production gate:** Phase 08 proves objectives, security, rollback, and runbook readiness.

## Definition of done

- Functional and non-functional PRD acceptance checks pass.
- Stream fixtures are accepted by both backend and frontend.
- A double-submit produces one canonical user message/run.
- A disconnect resumes without missing or duplicating content.
- Stop is canonically confirmed and preserves partial content.
- Retry/regenerate semantics retain audit history and one visible answer.
- Cross-user access and Markdown XSS suites pass.
- No prompt/response content appears in standard telemetry.
- Production-like load, migration rollback, and incident runbooks are exercised.

## Deliberate V1 ceilings

- API process loss fails, rather than continues, active generations.
- Event following uses PostgreSQL rather than a dedicated pub/sub system.
- Conversations are linear with answer versions, not branch navigation.
- Provider selection is fixed per deployment.

Add queue/pub-sub workers, branching, or provider selection only when a concrete product or measured operational requirement crosses these ceilings.
