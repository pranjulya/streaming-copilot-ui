# Accessibility report (Phase 08)

Recorded 2026-09-23 by the Playwright journey `apps/web/tests/e2e/accessibility.spec.ts`,
which runs axe-core (4.13) in real Chromium against the running app.

## Results

| Surface | Violations |
|---|---|
| Conversation list (`/`) | 0 |
| Transcript with a completed answer (`/c/{id}`) | 0 |

Both runs include the default rule set (contrast, landmarks, names, roles). One
real finding was fixed while recording this report: the conversation list page had
no level-one heading (`page-has-heading-one`, moderate) — the list now renders a
`Conversations` `<h1>`.

## Standing checks

Each claim names the automated check that covers it. Checks without a named test
are not covered automatically and were verified by hand while recording this
report.

- Keyboard: `apps/web/tests/components/composer.test.tsx` — "Enter submits and
  clears, Shift+Enter inserts a newline" and "ignores IME Enter and refocuses
  after submit".
- Screen-reader shell: `apps/web/tests/shell.test.tsx` — "renders the app shell
  with the Copilot title link" asserts the polite live region.
- Transcript semantics: `apps/web/tests/components/transcript.test.tsx` asserts
  the message list is an ordered `role="list"`.
- Motion: `apps/web/tests/components/composer.test.tsx` — "token animation is
  disabled under prefers-reduced-motion".
- Markdown: `apps/web/tests/components/safe-markdown.test.tsx` — the XSS corpus
  renders no executable elements.

Not covered by a named test (hand-checked only): control-by-control keyboard
reachability and the screen-reader announcement of each `role="status"` message.

## Reproduce

```sh
cd apps/web
pnpm exec playwright test tests/e2e/accessibility.spec.ts
```

The journey waits for the conversation list to leave its "Loading conversations…"
state before `analyze()`, so the list run covers the populated list (links,
rename/archive controls), not just the loading shell. The counts above predate
that tightening and must be re-recorded on the next run.
