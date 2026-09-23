# Phase 08 — Verification and release

> Requires Phase 07. This phase **records** calibrated numbers; it does not invent architecture.

**Goal:** Load, evaluation, migration rollback, runbooks, and SLO evidence so V1 can be released.

**Spec:** `docs/PRD.md` §7 and §10, `docs/testing-and-evaluation.md`, `docs/production-scenarios.md`, `docs/configuration.md` §6.

## Files

- Create: `docs/operations/release-checklist.md` (evidence index; fill during this phase)
- Create: `services/api/tests/load/` or `k6/` script matching the 50-stream mix
- Create: `eval/set.json` small versioned prompts (no secrets)
- Modify: `.env.example` comments with **calibrated** timeout/batch/retention values after measurement

### Task 1: Load and backpressure

- [x] Run the mix: 50 concurrent streams, 5 creates/s, 70/20/10 complete/long/cancel.
- [x] Measure accept latency, service first-event (exclude provider), cancel ack, reconnect catch-up, DB pool, RSS per connection.
- [x] Confirm slow reader does not unbounded-buffer events (retention still bounds rows).
- [x] Write chosen `DELTA_FLUSH_*`, `EVENT_FOLLOW_POLL_MS`, `HEARTBEAT_INTERVAL_SECONDS`, timeouts, `EVENT_RETENTION_HOURS` into configuration docs.
- [x] Commit `docs: record calibrated streaming defaults`.

### Task 2: Migration rollback rehearsal

- [x] Backup/restore on a copy of the schema with sample runs.
- [x] Expand/contract dry-run: additive migration apply; app rollback; no destructive step in V1.
- [x] Commit `test: rehearse database restore`.

### Task 3: LLM evaluation (offline job)

- [x] Versioned eval set: context retention, refusal, Markdown, truncation.
- [x] FakeProvider remains the CI gate.
- [x] Live `grok-4.6` job is explicit/manual; compare to baseline; never assert exact free-form equality in merge CI.
- [x] Commit `test: add versioned eval set`.

### Task 4: SLO and security evidence

- [x] CI bundle: fixture suite, ownership matrix, XSS, idempotency double-submit, content-mismatch metric zero on soak.
- [x] Dashboard queries for PRD SLOs saved as text (no user content).
- [x] Accessibility report (Playwright + axe).
- [x] Commit `docs: attach release evidence index`.

### Task 5: Runbook dry-run

- [x] Walk scenarios 1–14 with the operator template.
- [x] Named owner approval recorded in the checklist (human).
- [x] Stop. Do not ship if any Phase 00–07 gate is red.

## Stop gate

Release checklist complete: CI, restore, load report, eval comparison, scans, a11y, dashboards, rollback, owner approval. Planning-calibrated values are no longer placeholders in runtime config.
