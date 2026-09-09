# AGENTS.md

Project rules for any coding agent working in this repository. Do not copy the specs here; follow them.

## Status

This repo is **planning-complete, implementation-not-started**. Do **not** scaffold `apps/`, `services/`, or `contracts/` until the user **explicitly approves** the planning package in the conversation.

After approval, implement **one phase at a time** from `implementation/phase-00-foundation-and-contracts.md` onward. Stop at each phase gate.

## Required reading (in order)

1. `README.md` — locked decisions and package index
2. `docs/PRD.md`, `docs/HLD.md`, `docs/LLD.md`
3. `docs/api-and-stream-contracts.md`, `docs/persistence-model.md`, `docs/state-machine.md`
4. `docs/configuration.md` — env names, versions, local topology
5. `Implementation.md` then the current `implementation/phase-0N-*.md`

If a plan conflicts with an approved spec, **stop and amend the spec** before writing code.

## Execution

- Use `superpowers:subagent-driven-development` or `superpowers:executing-plans`.
- TDD: failing check → minimal code → focused check → phase suite → phase-scoped commit.
- Do not mix later-phase features into an earlier phase.
- Do not invent Redis, queues, WebSockets, SSE, tools, RAG, attachments, or a second LLM provider.

## Stack (V1)

- Web: Next.js 15, React 19, TypeScript, `pnpm`, same-origin rewrite to the API
- API: Python 3.12, FastAPI, SQLAlchemy 2, Alembic
- State: PostgreSQL 16 only
- Stream: `POST` + Fetch `ReadableStream` + typed NDJSON (`application/x-ndjson`)
- Provider: xAI `grok-4.6` in production; `FakeProvider` in CI and keyless local
- Tests: pytest (real Postgres), Vitest, Playwright

## Invariants

- Authenticated `Actor.user_id` on every `/v1` query; missing/not-owned → `404` (not `403`)
- Idempotency on create/patch/send/retry/regenerate; cancel has no idempotency key
- One active run per conversation; per-user active-run cap
- Generation owner lease stamped in the create/retry/regenerate transaction; every replica reaps expired/NULL leases on a timer
- Heartbeats are connection-only; `response.snapshot` is synthesized, not stored
- Terminal assistant content is immutable; retry and regenerate insert a new visible version
- Model output is data: sanitize Markdown; never log prompt/response content

## Layout (created by phase)

```text
apps/web/          # Phase 00+
services/api/      # Phase 00+
contracts/         # Phase 00 fixtures + JSON Schema + openapi.yaml snapshot (no codegen)
docs/              # specifications
implementation/    # phase plans
```

Local: API `127.0.0.1:8000`, web `127.0.0.1:3000`, Postgres `5432`. See `docs/configuration.md`.
