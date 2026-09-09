# Low-Level Design

## 1. Planned repository structure

```text
streaming-copilot-ui/
├── apps/web/
│   ├── app/
│   ├── features/chat/
│   │   ├── api/
│   │   ├── components/
│   │   ├── state/
│   │   └── stream/
│   └── tests/
├── services/api/
│   ├── app/
│   │   ├── api/
│   │   ├── chat/
│   │   ├── persistence/
│   │   ├── providers/
│   │   └── observability/
│   └── tests/
├── contracts/
│   ├── examples/
│   └── stream-events.schema.json
├── docs/
├── Learning/
├── implementation/
└── Implementation.md
```

Directories are introduced only in the phase that needs them. No shared package, monorepo framework, provider registry, or generic event bus is planned.

## 2. Frontend interfaces

### Stream parser

```ts
type ParseResult =
  | { kind: "event"; event: StreamEvent }
  | { kind: "invalid"; line: string; reason: string };

async function* parseNdjson(
  body: ReadableStream<Uint8Array>,
  signal: AbortSignal,
): AsyncGenerator<ParseResult>;
```

Algorithm:

1. Read bytes with the stream reader.
2. Decode using one streaming `TextDecoder` so split UTF-8 code points remain valid.
3. Append decoded text to a carry buffer.
4. Split only on newline and retain the incomplete suffix.
5. Parse and minimally validate each non-empty line.
6. On normal EOF, parse a final non-empty suffix; malformed content is a protocol error.
7. Release the reader lock in `finally`.

### Chat reducer

```ts
type ChatAction =
  | { type: "turn.optimistic"; turn: OptimisticTurn }
  | { type: "stream.event"; event: StreamEvent }
  | { type: "stream.disconnected"; runId: string; error: ClientError }
  | { type: "history.reconciled"; snapshot: ConversationSnapshot };

function chatReducer(state: ChatState, action: ChatAction): ChatState;
```

The reducer is pure. Network code dispatches actions but does not mutate transcript state. Each run keeps `lastSequence`, phase, server IDs, partial content, and last recoverable error.

### Conversation client

```ts
function createConversation(input: { title?: string }, key: string): Promise<Conversation>;
function listConversations(query: { cursor?: string; limit?: number; includeArchived?: boolean }): Promise<Page<Conversation>>;
function getConversation(id: string, query?: { cursor?: string; limit?: number }): Promise<ConversationSnapshot>;
function patchConversation(id: string, patch: { title?: string; archived?: boolean }, key: string): Promise<Conversation>;
function startResponse(input: StartResponseInput, signal: AbortSignal): Promise<Response>;
function followResponse(runId: string, afterSequence: number, signal: AbortSignal): Promise<Response>;
function cancelResponse(runId: string, signal: AbortSignal): Promise<RunSnapshot>;
function retryResponse(runId: string, key: string, signal: AbortSignal): Promise<Response>; // NDJSON stream
function regenerateResponse(userMessageId: string, key: string, signal: AbortSignal): Promise<Response>; // NDJSON stream
function getRun(id: string): Promise<RunSnapshot>;
```

Errors become a discriminated `ClientError` with `kind`, HTTP status, stable server code, retryability, and diagnostic ID.

## 3. Backend interfaces

### Actor

```python
@dataclass(frozen=True)
class Actor:
    user_id: str
    auth_method: Literal["jwt", "cookie", "dev"]
```

Routes extract `Actor` from the auth adapter. Services never read identity from request bodies.

### Provider boundary

```python
@dataclass(frozen=True)
class ProviderDelta:
    text: str = ""
    finish_reason: str | None = None  # stop | length | None while streaming
    usage: Usage | None = None
    error: ProviderError | None = None

class LlmProvider(Protocol):
    def stream(
        self,
        messages: Sequence[ProviderMessage],
        *,
        signal: CancelSignal,
    ) -> AsyncIterator[ProviderDelta]: ...
```

Text-only deltas carry `text`. The iterator ends with a delta that has `finish_reason` and final `usage`, or raises/`error` for provider failure. The adapter never yields chain-of-thought or tool calls; those are dropped.

V1 production adapter talks to xAI at `https://api.x.ai/v1` using `XAI_API_KEY` and the configured `XAI_MODEL` (default `grok-4.6`). Prefer the Responses API with `stream=true`; map output text deltas into `ProviderDelta`. A scripted `FakeProvider` is injected in tests and local demos when `XAI_API_KEY` is unset and `APP_ENV=development`.

Start with one concrete provider passed directly into the response service. Introduce a selector only when a second runtime provider is required.

### Response service

```python
async def create_run(command: CreateRun, actor: Actor) -> RunHandle: ...
async def retry_run(run_id: UUID, key: UUID, actor: Actor) -> RunHandle: ...
async def regenerate(user_message_id: UUID, key: UUID, actor: Actor) -> RunHandle: ...
async def request_cancel(run_id: UUID, actor: Actor) -> RunSnapshot: ...
async def follow_events(run_id: UUID, after_sequence: int, actor: Actor) -> AsyncIterator[StreamEvent]: ...
```

The route owns response headers and line serialization. The service owns authorization-aware resource lookup, idempotency, transitions, and transactions.

### Event writer

```python
async def start_run(run_id: UUID) -> StreamEvent: ...
async def append_delta(run_id: UUID, delta: str) -> StreamEvent: ...
async def append_usage(run_id: UUID, usage: Usage) -> StreamEvent: ...
async def complete_run(run_id: UUID, result: CompletionResult) -> tuple[StreamEvent, StreamEvent]: ...
async def fail_run(run_id: UUID, failure: SafeFailure) -> StreamEvent: ...
async def cancel_run(run_id: UUID) -> StreamEvent: ...
```

`start_run` transitions `queued → streaming`, inserts `response.started` as sequence `1`, and is idempotent if already `streaming`. `append_usage` writes `usage.updated` without changing message content. `cancel_run` sets assistant `status=cancelled`, freezes content, and commits the single terminal `response.cancelled` (no `message.completed`).

Each method locks the run row and atomically updates run/message state with events. Terminal methods are idempotent: they return the existing terminal event if already terminal.

### Generation supervisor

```python
class GenerationSupervisor:
    async def start(self, run_id: UUID) -> None: ...
    async def shutdown(self, grace_seconds: float) -> None: ...
```

It maintains only local task handles. Authoritative status remains in PostgreSQL.

Each process has a boot-time `INSTANCE_ID` (random UUID unless configured). **Live processes must not share an `INSTANCE_ID`.** The create/retry/regenerate transaction is the first lease writer. `start` only renews an existing lease; it does not claim NULL rows.

The supervisor loop renews on `LEASE_RENEW_SECONDS`. **Every live replica** runs two distinct orphan-recovery paths:

1. **Startup only:** fail non-terminal runs this instance owns, even if the lease has not expired (covers a crash/restart that reused a stable `INSTANCE_ID` before expiry).
2. **Periodic timer `≤ LEASE_SECONDS`:** fail only non-terminal runs with `lease_expires_at IS NULL` or `lease_expires_at < now()`. Do **not** fail unexpired leases owned by this instance; the live supervisor is renewing them.

A live unexpired lease owned by another instance is left alone. After process death with a new instance id, the run becomes terminal within one lease interval plus one reaper tick. Any replica may set `cancel_requested_at`; the owner observes it at the next delta/lease tick.

## 4. Streaming mechanics

- The provider task writes deltas in bounded batches: flush on a small time interval or content threshold, whichever comes first. Exact values are configuration calibrated in Phase 08 load tests.
- The follower reads committed events above its cursor and waits with bounded polling. PostgreSQL `LISTEN/NOTIFY` may replace polling only if measurements show the need; correctness cannot depend on notifications.
- HTTP proxy buffering is disabled for NDJSON routes.
- Every serialized record ends in newline and is flushed promptly.
- Heartbeats are connection-only: they are not stored, do not increment `sequence`, and carry `last_sequence`. See `docs/api-and-stream-contracts.md`.
- The server emits `\n` (LF) after every record. The parser also accepts `\r\n` so a misbehaving proxy cannot corrupt framing.
- Backpressure naturally awaits the HTTP sender; durable generation continues within bounded event retention even if one client is slow.

## 5. Context construction

V1 sends a system instruction plus the newest turns that fit `CONTEXT_CHAR_BUDGET`. Each turn is the user message plus the **visible** assistant message (`is_visible=true`). Hidden regenerated/retried versions are omitted. Visible cancelled or failed assistants are included only when content is non-empty. Failed empty assistants are omitted. UI-only status text is never sent. Truncation removes oldest complete turns first and records counts, not content, in telemetry.

Token counting uses the selected provider's supported counter when available; a conservative character-based ceiling is the fallback. Summarization memory is deferred.

## 6. Error mapping

| Source | Public code | Retryable | Result |
|---|---|---:|---|
| Invalid input | `validation_failed` | No | HTTP problem before stream |
| Missing/not owned | `not_found` | No | HTTP 404 |
| Active run | `conversation_busy` | No | HTTP 409 |
| Auth missing/invalid | `unauthenticated` | No | HTTP 401 |
| Idempotency mismatch | `idempotency_key_conflict` | No | HTTP 409 |
| Archived conversation | `conversation_archived` | No | HTTP 409 |
| Per-user active-run cap | `too_many_active_runs` | No | HTTP 409 |
| Illegal retry/regenerate | `invalid_run_state` | No | HTTP 409 |
| Orphan after process loss | `server_restart` | Yes | Failed event |
| Provider down | `provider_unavailable` | Yes | Failed event |
| Rate limit | `rate_limited` | Yes | HTTP 429 with bounded retry hint |
| Provider 429 | `provider_rate_limited` | Yes | Failed event |
| Provider timeout | `provider_timeout` | Yes | Failed event |
| Malformed provider data | `provider_protocol_error` | Yes | Failed event |
| Database unavailable | `service_unavailable` | Yes | Problem or failed event |
| Client NDJSON failure | `stream_protocol_error` | Reconcile | Client recovery path |

Unexpected exceptions receive a diagnostic ID; raw exception text is never sent to the browser.

## 7. Configuration boundary

Named settings live in `docs/configuration.md`. Defaults exist only for safe local development. Secrets are required in non-development environments and never exposed through client bundles. V1 has **no feature flags**; behavior is configuration and code.

## 7a. Runtime versions

| Piece | V1 floor |
|---|---|
| Python | 3.12 |
| Node.js | 22 LTS |
| Next.js | 15 |
| React | 19 |
| FastAPI | 0.115+ |
| SQLAlchemy | 2.x |
| Alembic | 1.x |
| PostgreSQL | 16 |
| pytest / Vitest / Playwright | current stable at Phase 00 pin |

## 7b. Markdown rendering

The web app renders assistant Markdown with `react-markdown` and `rehype-sanitize` (default schema, no raw HTML, `javascript:` links stripped). Do not use `dangerouslySetInnerHTML`.

## 8. Accessibility details

- Transcript uses semantic list/article structure and stable message labels.
- A polite live region announces coarse states such as “Assistant started responding” and “Response complete,” never token deltas.
- Stop/send controls have stable accessible names and disabled reasons.
- Focus returns to the composer after send; errors focus a concise summary only when user action is required.
