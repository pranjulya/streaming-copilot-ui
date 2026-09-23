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

- Keyboard: Enter submits, Shift+Enter inserts a newline, every control is
  reachable and operable by keyboard (unit tests in `apps/web/tests/components`).
- Screen readers: the shell exposes a polite live region; run status is announced
  through `role="status"` regions; messages are a semantic ordered list.
- Motion: `prefers-reduced-motion` disables the token-pulse animation.
- Markdown: assistant output is sanitized; the XSS corpus renders no executable
  elements.

## Reproduce

```sh
cd apps/web
pnpm exec playwright test tests/e2e/accessibility.spec.ts
```
