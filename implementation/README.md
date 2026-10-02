# Implementation Phase Index

This directory is an execution map, not application code. Read `../Implementation.md` and all specifications before starting.

## Approval state

**APPROVED:** Planning and Phase 00 authorized 2026-09-19 at `53c1b7c`. Phases 00 and 01 are on `main` ([PR #1](https://github.com/pranjulya/streaming-copilot-ui/pull/1), [PR #4](https://github.com/pranjulya/streaming-copilot-ui/pull/4)). Stop at the Phase 01 review gate before Phase 02.

## Phases

1. [Phase 00 — Foundation and contracts](phase-00-foundation-and-contracts.md)
2. [Phase 01 — Persistence and conversation API](phase-01-persistence-and-conversations.md)
3. [Phase 02 — Response lifecycle and event store](phase-02-response-lifecycle.md)
4. [Phase 03 — Provider streaming](phase-03-provider-streaming.md)
5. [Phase 04 — Frontend chat and history](phase-04-frontend-chat.md)
6. [Phase 05 — End-to-end streaming](phase-05-end-to-end-streaming.md)
7. [Phase 06 — Resilience and lifecycle controls](phase-06-resilience-controls.md)
8. [Phase 07 — Production guardrails](phase-07-production-guardrails.md)
9. [Phase 08 — Verification and release](phase-08-verification-release.md)

## Execution rules

- Complete phases in order; later plans name interfaces produced earlier.
- Begin each task with its failing or absent-behavior check, implement the minimum, run the focused check, then run the phase suite.
- Keep commits phase-scoped and do not mix refactors or later capabilities.
- When a plan conflicts with an approved specification, stop and amend the design before code.
- Record calibrated timeout/batch/retention values during Phase 08; do not silently guess production defaults.

## Completion ledger

| Phase | Status | Approval evidence |
|---:|---|---|
| Planning | Approved | Explicit user approval, 2026-09-19, baseline `53c1b7c` |
| 00 | On `main` ([PR #1](https://github.com/pranjulya/streaming-copilot-ui/pull/1)) | Phase 00 explicitly authorized 2026-09-19 |
| 01 | On `main`; pending gate review ([PR #4](https://github.com/pranjulya/streaming-copilot-ui/pull/4)) | Merged; review before Phase 02 |
| 02–08 | On their branches, not on `main` | Phase 01 gate remains |
