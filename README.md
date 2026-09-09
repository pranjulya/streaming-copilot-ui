# Project 6 — Streaming Copilot UI

Planning-only repository for a full chat-style Copilot with persistent history and typed NDJSON streaming.

Agent entrypoint: [`AGENTS.md`](AGENTS.md) (required at repo root for Grok/SOL and other coding agents).

## Status

**Planning package expanded and awaiting approval; implementation not started.** Phase 00 is blocked until this package is reviewed and explicitly approved.

## Locked decisions

- Next.js/React frontend
- FastAPI backend
- `POST` streaming through `fetch()` and `ReadableStream`
- `AbortController` for client-side stream cancellation
- Server-side persistent conversation history
- Versioned typed NDJSON events
- xAI (`grok-4.6`) as the single V1 production provider; `FakeProvider` in tests
- Generation owner leases for multi-replica safety

## Planning package

- [Agent project rules](AGENTS.md)

- [Product requirements](docs/PRD.md)
- [High-level design](docs/HLD.md)
- [Low-level design](docs/LLD.md)
- [Architecture diagrams](docs/architecture-diagrams.md)
- [API and stream contracts](docs/api-and-stream-contracts.md)
- [State machines](docs/state-machine.md)
- [Persistence model](docs/persistence-model.md)
- [Resilience and reconciliation](docs/resilience-and-reconciliation.md)
- [Observability](docs/observability.md)
- [Security](docs/security.md)
- [Testing and evaluation](docs/testing-and-evaluation.md)
- [Production scenarios](docs/production-scenarios.md)
- [Architecture decisions](docs/decisions.md)
- [Configuration and local runtime](docs/configuration.md)
- [Requirements traceability](docs/traceability.md)
- [Glossary](docs/glossary.md)
- [Learning path](Learning/learning-path.md)
- [Questions and answers](Learning/questions-and-answers.md)
- [Master implementation blueprint](Implementation.md)
- [Phase index](implementation/README.md)
- Phases 00–08 under `implementation/phase-0*.md`
- [Planning review (approve, 0 open issues)](docs/_planning-review.md)

## Review gate

Review the documents above, resolve any requested changes, and record approval in the project conversation. Only then may Phase 00 begin.
