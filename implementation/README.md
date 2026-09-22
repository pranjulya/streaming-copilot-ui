# Implementation Phase Index

This directory is an execution map, not application code. Read `../Implementation.md` and all specifications before starting.

## Approval state

**APPROVED:** the user explicitly approved the full planning package and Phase 00 on 2026-09-19 at `53c1b7c`. Stop at the Phase 00 review gate before Phase 01.

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
| 00 | Implementation under verification | Phase 00 explicitly authorized in the same conversation |
| 01 | Implemented; pending gate review | TDD complete on `phase-01-persistence-and-conversations` (3 phase-scoped commits) |
| 02–08 | Not started | Phase 01 gate remains |
