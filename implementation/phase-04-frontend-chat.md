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

- [ ] Implement list/get/create/patch from LLD client signatures (non-streaming).
- [ ] Map 401/404/409/429 to `ClientError`.
- [ ] MSW or fetch mock tests. Commit `feat: add conversation http client`.

### Task 2: List and transcript without streaming

- [ ] Routes: `/` list, `/c/[id]` transcript.
- [ ] Empty state, loading, error summary.
- [ ] Archive requires confirm; undo via `archived: false`.
- [ ] Rename inline.
- [ ] Commit `feat: render conversation list and history`.

### Task 3: Composer and a11y

- [ ] Enter submits; Shift+Enter newline; button available.
- [ ] Composer **does not call a write API** in this phase (there is no `POST /v1/messages`). Submit may no-op or dispatch an optimistic local action that Phase 05 will replace with `startResponse`.
- [ ] Polite live region exists in the DOM (can stay empty until stream states exist).
- [ ] `prefers-reduced-motion` disables token animation CSS.
- [ ] Semantic list for messages; no `dangerouslySetInnerHTML`.
- [ ] axe-core unit checks on Transcript + Composer.
- [ ] Commit `feat: add accessible composer and chat shell`.

### Task 4: Sanitized Markdown

- [ ] `react-markdown` + `rehype-sanitize`.
- [ ] XSS corpus: `<script>`, `javascript:` links, raw HTML — not executed.
- [ ] Commit `feat: sanitize assistant markdown`.

## Stop gate

UI unit and accessibility checks pass **without** a live provider. Keyboard and screen-reader status hooks are present.
