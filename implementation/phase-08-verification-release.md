# Phase 08 — Verification and release

> Requires Phase 07. This phase **records** calibrated numbers; it does not invent architecture.

**Goal:** Load, evaluation, migration rollback, runbooks, and SLO evidence so V1 can be released.

**Spec:** `docs/PRD.md` §7 and §10, `docs/testing-and-evaluation.md`, `docs/production-scenarios.md`, `docs/configuration.md` §6.

## Files

- Create: `docs/operations/release-checklist.md` (evidence index; fill during this phase)
- Create: `services/api/tests/load/` or `k6/` script matching the 50-stream mix
- Create: `eval/set.json` small versioned prompts (no secrets)
- Modify: `.env.example` comments with timeout/batch/retention values (uncalibrated until a soak)

### Task 1: Load and backpressure

- [x] Harness assigns 50 streams at 5 creates/s with 70/20/10 complete/long/cancel (production-like soak outstanding).
- [x] Measure accept, first NDJSON event, cancel ack, reconnect first-byte, HTTP errors, harness RSS, peak in-flight.
- [x] Compact terminal `stream_events` older than `EVENT_RETENTION_HOURS`; follow synthesizes snapshot.
- [x] Record local defaults in configuration docs as uncalibrated until a soak is attached.
- [x] Commit `docs: record calibrated streaming defaults`.

### Task 2: Migration rollback rehearsal

- [x] Backup/restore on a copy of the test database's schema, tables, and rows.
- [x] Expand/contract dry-run: additive migrations apply to the restored copy; no destructive step in V1.
- [ ] App rollback rehearsal: run the previous app image against the migrated schema. Needs Docker and the previous image, so it is deferred; see the rollback note in `docs/operations/release-checklist.md`.
- [x] Commit `test: rehearse database restore`.

### Task 3: LLM evaluation (offline job)

- [x] Versioned eval set: context retention, refusal, Markdown, truncation.
- [x] FakeProvider remains the CI gate.
- [x] Live `grok-4.6` job is explicit/manual; compare to baseline; never assert exact free-form equality in merge CI.
- [x] Commit `test: add versioned eval set`.

### Task 4: SLO and security evidence

- [x] CI bundle: fixture suite, ownership matrix, XSS, idempotency double-submit; the load harness compares streamed vs stored assistant length client-side.
- [x] Dashboard queries for PRD SLOs saved as text (no user content).
- [x] Accessibility report (Playwright + axe).
- [x] Commit `docs: attach release evidence index`.

### Task 5: Runbook dry-run

- [x] Walk scenarios 1–14 with the operator template.
- [ ] Named owner approval recorded in the checklist (human).
- [x] Stop. Do not ship if any Phase 00–07 gate is red.

## Stop gate

Release checklist complete: CI, restore, load report, eval comparison, scans, a11y, dashboards, rollback, owner approval. Planning-calibrated values are no longer placeholders in runtime config.

**Still open at this tip:** the production-like 50-in-flight soak (so §7 stays uncalibrated), the live `grok-4.6` eval baseline/comparison (`eval/baseline.json` is unrecorded), the app-image rollback rehearsal, and named owner approval. The stop gate stays red until those are recorded.
