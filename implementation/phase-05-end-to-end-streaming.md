# Phase 05 — End-to-end typed streaming

> Requires Phases 03 and 04.

**Goal:** Browser parses NDJSON (including split chunks), reducer applies events, optimistic IDs reconcile, reload shows canonical text.

**Spec:** `docs/LLD.md` parser/reducer, `docs/resilience-and-reconciliation.md` §2–3, contracts events.

## Files

- Create: `apps/web/features/chat/stream/parseNdjson.ts`
- Create: `apps/web/features/chat/state/chatReducer.ts`, `types.ts`
- Create: `apps/web/features/chat/api/stream.ts`
- Test: `apps/web/tests/stream/parseNdjson.test.ts`, `apps/web/tests/state/chatReducer.test.ts`
- E2E: `apps/web/tests/e2e/stream-complete.spec.ts`

### Task 1: NDJSON parser

```ts
async function* parseNdjson(body: ReadableStream<Uint8Array>, signal: AbortSignal): AsyncGenerator<ParseResult>
```

- [ ] Tests with `TextEncoder` chunks: one event split in three; two events in one chunk; multibyte `é` split; supplementary-plane `👍` in a delta; `content_index` via `Array.from(content).length`; CRLF tolerance; empty lines ignored; invalid JSON → `invalid`; abort releases reader; unknown type yields event for reducer to ignore; unsupported major version → invalid/protocol.
- [ ] Implement with one `TextDecoder({ stream: true })` and carry buffer.
- [ ] Commit `feat: parse ndjson with streaming utf-8`.

### Task 2: Reducer

```ts
function chatReducer(state: ChatState, action: ChatAction): ChatState
```

- [ ] Optimistic turn then `response.started` maps IDs.
- [ ] Duplicate sequence ignored; gap does not append (sets reconciling).
- [ ] `content_index` mismatch → reconciling.
- [ ] `message.completed` replaces accumulation.
- [ ] Unknown type: no state change.
- [ ] `response.snapshot` replaces content and `lastSequence`.
- [ ] Heartbeat ignored.
- [ ] Navigation does not clear another conversation’s run state.
- [ ] Commit `feat: add deterministic chat reducer`.

### Task 3: Wire startResponse to UI

- [ ] Generate `client_message_id` and `Idempotency-Key` before fetch.
- [ ] POST stream, parse, dispatch.
- [ ] Disable proxy buffering is server-side already.
- [ ] Commit `feat: stream assistant deltas in the transcript`.

### Task 4: Playwright complete journey

- [ ] FakeProvider in API test config.
- [ ] New conversation → send “Explain backpressure…” → deltas appear → reload → same canonical text and IDs.
- [ ] Split-chunk covered at unit level; e2e asserts visible final string.
- [ ] Commit `test: e2e streamed completion and reload`.

## Stop gate

Browser streams split chunks and reloads the canonical result. Contract fixtures are accepted by the parser.
