# V1 release checklist (Phase 08)

Fill during this phase; every line links to its evidence. The last line is a human
approval — an agent must not tick it.

## Gates

- [x] Phase 00–07 gates green (all PRs merged or open with green CI)
- [x] CI bundle: contract fixtures, ownership matrix, XSS corpus, idempotency
      double-submit, rate limits, CORS/CSRF, log-redaction — see the workflow in
      `.github/workflows/ci.yml` and the suites under `services/api/tests` and
      `apps/web/tests`
- [x] Test suites: API **141 passed** (1 opt-in live skip), web **69 passed**,
      Playwright **6 journeys** (stream completion, cancel, reconnect,
      retry/regenerate, ambiguous send, axe accessibility)
- [x] Schema drift: `alembic check` reports no new upgrade operations
- [x] Restore rehearsal: `scripts/rehearse_restore.sh` round-trips the database and
      re-applies migrations at head (`services/api/tests/test_restore_rehearsal.py`)
- [x] Load report: `docs/operations/load-report.md` — 50 streams, 5 creates/s,
      70/20/10 mix; accept p95 16.5 ms, first event p95 71 ms, cancel ack p95
      7.1 ms, 0 errors, `content_mismatch_total` 0
- [x] Evaluation: versioned set in `eval/set.json`; FakeProvider is the CI gate
      (`services/api/tests/test_eval_set.py`); live `grok-4.6` run is manual
- [x] Scans: `pip-audit` clean, `pnpm audit --audit-level high` clean (postcss
      override), gitleaks job in CI
- [x] Accessibility: `docs/operations/accessibility-report.md` — 0 axe violations
      on list and transcript in Chromium
- [x] Dashboards: `docs/operations/dashboards.md` (text queries, no user content)
- [x] Runbook dry-run: `docs/operations/runbook.md` covers scenarios 1–14
- [x] Calibrated values recorded: `docs/configuration.md` §7; `.env.example`
      comments updated
- [ ] **Named owner approval** — human sign-off before release (not an agent step)

## Rollback position

V1 is forward-only: the additive migrations tolerate the previous app image; a bad
deploy rolls back by shipping the previous image. The destructive path (event
compaction policy changes, retention lowering) requires a new rehearsal.
