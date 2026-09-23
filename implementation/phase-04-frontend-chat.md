# Phase 04 — Frontend chat and history

> Requires Phase 01 API. Does **not** require live generation. History UI talks to JSON endpoints only.

**Goal:** Accessible chat shell: conversation list, transcript, composer, status text, archive confirm.

**Spec:** `docs/PRD.md` UX, `docs/LLD.md` a11y, `docs/api-and-stream-contracts.md` resource JSON.

## Files

- Create: `apps/web/app/page.tsx` (list), `apps/web/app/c/[id]/page.tsx`
- Create: `apps/web/features/chat/api/client.ts`
- Create: `apps/web/features/chat/components/{AppShell,ConversationList,Transcript,Composer,MessageBubble,StatusText}.tsx`
- Create: `apps/web/features/chat/markdown/SafeMarkdown.tsx`
- Test: `apps/web/tests/components/*.test.tsx`

### Task 1: Typed JSON client

- [x] Implement list/get/create/patch from LLD client signatures (non-streaming).
- [x] Map 401/404/409/429 to `ClientError`.
- [x] MSW or fetch mock tests. Commit `feat: add conversation http client`.

### Task 2: List and transcript without streaming

- [x] Routes: `/` list, `/c/[id]` transcript.
- [x] Empty state, loading, error summary.
- [x] Archive requires confirm; undo via `archived: false`.
- [x] Rename inline.
- [x] Commit `feat: render conversation list and history`.

### Task 3: Composer and a11y

- [x] Enter submits; Shift+Enter newline; button available.
- [x] Composer **does not call a write API** in this phase (there is no `POST /v1/messages`). Submit may no-op or dispatch an optimistic local action that Phase 05 will replace with `startResponse`.
- [x] Polite live region exists in the DOM (can stay empty until stream states exist).
- [x] `prefers-reduced-motion` disables token animation CSS.
- [x] Semantic list for messages; no `dangerouslySetInnerHTML`.
- [x] axe-core unit checks on Transcript + Composer.
- [x] Commit `feat: add accessible composer and chat shell`.

### Task 4: Sanitized Markdown

- [x] `react-markdown` + `rehype-sanitize`.
- [x] XSS corpus: `<script>`, `javascript:` links, raw HTML — not executed.
- [x] Commit `feat: sanitize assistant markdown`.

## Stop gate

UI unit and accessibility checks pass **without** a live provider. Keyboard and screen-reader status hooks are present.
