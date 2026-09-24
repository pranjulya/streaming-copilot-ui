# V1 release checklist (Phase 08)

Fill during this phase; every line links to its evidence. The last line is a human
approval — an agent must not tick it.

## Gates

- [x] Phase 00–07 gates green (all PRs merged or open with green CI)
- [x] CI bundle: contract fixtures, ownership matrix, XSS corpus, idempotency
      double-submit, rate limits, CORS/CSRF, log-redaction — see the workflow in
      `.github/workflows/ci.yml` and the suites under `services/api/tests` and
      `apps/web/tests`
- [x] Test suites: API **181 passed** (1 opt-in live skip) with
      `REHEARSE_RESTORE=1`, web **92 passed**, Playwright **6 journeys**
      (stream completion, cancel, reconnect, retry/regenerate, ambiguous send,
      axe accessibility)
- [ ] Schema drift: CI runs `alembic upgrade head`; `alembic check` is not a CI step
- [x] Restore rehearsal: `scripts/rehearse_restore.sh` dumps, restores into a
      scratch database, runs alembic against that scratch URI, and requires
      `alembic current` to report `(head)` (`services/api/tests/test_restore_rehearsal.py`;
      CI sets `REHEARSE_RESTORE=1`)
- [ ] Load report: harness assigns 70/20/10 and records peak in-flight
      (`services/api/tests/load/load_stream_mix.py`); a production-like
      50-in-flight soak is **not** attached — `docs/operations/load-report.md`
- [x] Evaluation: versioned set `eval/set.json` (`2026-09-24.1`) covers
      multi-turn context, refusal, Markdown, truncation, instruction hierarchy,
      and a domain question; FakeProvider is the CI gate
      (`services/api/tests/test_eval_set.py`); live `grok-4.6` baseline file
      exists and is unrecorded (`eval/baseline.json`)
- [x] Scans: `pip-audit` clean, `pnpm audit --audit-level high` clean (postcss
      override), gitleaks job in CI
- [x] Accessibility: `docs/operations/accessibility-report.md` — 0 axe violations
      on list and transcript in Chromium
- [x] Dashboards: `docs/operations/dashboards.md` (text queries, no user content;
      several histograms are registered and not emitting in V1)
- [x] Runbook dry-run: `docs/operations/runbook.md` covers scenarios 1–14
- [ ] Calibrated values: local defaults remain uncalibrated
      (`docs/configuration.md` §7)
- [ ] **Named owner approval** — human sign-off before release (not an agent step)

## Rollback position

V1 is forward-only: the additive migrations tolerate the previous app image; a bad
deploy rolls back by shipping the previous image. The destructive path (event
compaction policy changes, retention lowering) requires a new rehearsal.
