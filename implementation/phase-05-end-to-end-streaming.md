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

- [x] Tests with `TextEncoder` chunks: one event split in three; two events in one chunk; multibyte `é` split; supplementary-plane `👍` in a delta; `content_index` via `Array.from(content).length`; CRLF tolerance; empty lines ignored; invalid JSON → `invalid`; abort releases reader; unknown type yields event for reducer to ignore; unsupported major version → invalid/protocol.
- [x] Implement with one `TextDecoder({ stream: true })` and carry buffer.
- [x] Commit `feat: parse ndjson with streaming utf-8`.

### Task 2: Reducer

```ts
function chatReducer(state: ChatState, action: ChatAction): ChatState
```

- [x] Optimistic turn then `response.started` maps IDs.
- [x] Duplicate sequence ignored; gap does not append (sets reconciling).
- [x] `content_index` mismatch → reconciling.
- [x] `message.completed` replaces accumulation.
- [x] Unknown type: no state change.
- [x] `response.snapshot` replaces content and `lastSequence`.
- [x] Heartbeat ignored.
- [x] Navigation does not clear another conversation’s run state.
- [x] Commit `feat: add deterministic chat reducer`.

### Task 3: Wire startResponse to UI

- [x] Generate `client_message_id` and `Idempotency-Key` before fetch.
- [x] POST stream, parse, dispatch.
- [x] Disable proxy buffering is server-side already.
- [x] Commit `feat: stream assistant deltas in the transcript`.

### Task 4: Playwright complete journey

- [x] FakeProvider in API test config.
- [x] New conversation → send “Explain backpressure…” → deltas appear → reload → same canonical text and IDs.
- [x] Split-chunk covered at unit level; e2e asserts visible final string.
- [x] Commit `test: e2e streamed completion and reload`.

## Stop gate

Browser streams split chunks and reloads the canonical result. Contract fixtures are accepted by the parser.
