# API and Stream Contracts

## 1. Conventions

- Base path: `/v1`
- JSON requests/responses: `application/json`
- Streaming responses: `application/x-ndjson; charset=utf-8`
- IDs: UUID strings generated client-side only where noted; canonical IDs are server-generated UUIDs.
- Times: UTC RFC 3339 strings.
- Pagination: opaque `next_cursor`; clients do not parse cursors.
- Errors before streaming starts: RFC 9457-style `application/problem+json`.
- Errors after headers are sent: terminal `response.failed` event.
- Mutating retries send `Idempotency-Key`; keys are reused only for the same logical operation.
- Authentication is required on every `/v1` route. Health routes are unauthenticated and must not be exposed on the product edge except `/health/live` if a load balancer requires it.

### Authentication

| Environment | Mechanism | Actor `user_id` |
|---|---|---|
| `development` | Optional `X-Dev-User: <non-empty string>` or configured `DEV_USER_ID` | Header value, else `DEV_USER_ID` |
| `production` / `staging` | Host JWT in `Authorization: Bearer <token>`, or the same JWT in cookie `AUTH_COOKIE_NAME` when that setting is set | JWT `sub` (or `AUTH_JWT_SUBJECT_CLAIM`) |

`X-Dev-User` is rejected unless `APP_ENV=development`. Production configuration that enables the development identity adapter must fail startup.

When `AUTH_COOKIE_NAME` is set, the cookie is `HttpOnly; Secure; SameSite=Lax; Path=/` and holds the JWT (not an opaque session). Mutations authenticated by cookie (no `Authorization` header) **must** send `X-CSRF-Token` equal to a non-HttpOnly double-submit cookie `csrf_token`. `Origin` must be in `ALLOWED_ORIGINS`. Bearer-only requests do not require CSRF.

### Idempotency operations

The `operation` column stored with each key is one of:

| Operation | Endpoint |
|---|---|
| `create_conversation` | `POST /v1/conversations` |
| `create_response` | `POST /v1/conversations/{id}/responses` |
| `retry_run` | `POST /v1/response-runs/{id}/retry` |
| `regenerate_message` | `POST /v1/messages/{user_message_id}/regenerations` |
| `patch_conversation` | `PATCH /v1/conversations/{id}` |

`Idempotency-Key` is required on `POST /v1/conversations`, `PATCH /v1/conversations/{id}`, `POST .../responses`, `POST .../retry`, and `POST .../regenerations`. Missing or non-UUID keys return `400 validation_failed`. Cancel does **not** use an idempotency key; setting `cancel_requested_at` is naturally idempotent.

Request fingerprint is SHA-256 of `UTF-8(raw request body bytes) + "\n" + METHOD + "\n" + request path` (path includes the resource ids; query string is excluded). Clients must byte-for-byte reuse the body on retry. Replay with the same fingerprint returns the original result (JSON or the NDJSON stream of the existing run). Replay with a different fingerprint returns `409 idempotency_key_conflict`. After `IDEMPOTENCY_TTL_HOURS`, a reused key that still collides with `(conversation_id, client_message_id)` returns the existing user message’s run via that unique constraint path, never a 500.

### Pagination envelope

List endpoints accept `cursor` (opaque, optional) and `limit` (optional integer).

```json
{
  "items": [],
  "next_cursor": "opaque-or-null"
}
```

`next_cursor` is `null` when no further page exists. Default/max limits: conversations `20` / `100`; messages `50` / `100`. Out-of-range `limit` is `400 validation_failed`.

## 2. HTTP endpoints

| Method | Path | Success | Body |
|---|---|---|---|
| `POST` | `/v1/conversations` | 201 JSON | Conversation |
| `GET` | `/v1/conversations?cursor=&limit=&include_archived=` | 200 JSON | PaginationEnvelope of Conversation |
| `GET` | `/v1/conversations/{id}?cursor=&limit=` | 200 JSON | `{ conversation, messages, active_run }` |
| `PATCH` | `/v1/conversations/{id}` | 200 JSON | Conversation |
| `POST` | `/v1/conversations/{id}/responses` | 200 NDJSON | Stream (create-and-stream) |
| `POST` | `/v1/response-runs/{id}/stream` | 200 NDJSON | Stream from `after_sequence` |
| `GET` | `/v1/response-runs/{id}` | 200 JSON | RunSnapshot |
| `POST` | `/v1/response-runs/{id}/cancel` | 200 JSON | RunSnapshot |
| `POST` | `/v1/response-runs/{id}/retry` | 200 NDJSON | Stream of the **new** run (same as create-and-stream) |
| `POST` | `/v1/messages/{user_message_id}/regenerations` | 200 NDJSON | Stream of the **new** run |
| `GET` | `/health/live` | 200 JSON | `{ "status": "live" }` |
| `GET` | `/health/ready` | 200 JSON | `{ "status": "ready", "database": "ok" }` |

All resource endpoints apply ownership filtering in the query, returning `404` rather than revealing another user's resource.

Streaming endpoints additionally send:

```http
Cache-Control: no-cache, no-store
X-Accel-Buffering: no
Content-Type: application/x-ndjson; charset=utf-8
```

### Resource representations

Conversation:

```json
{
  "id": "uuid",
  "title": "Explain backpressure in streaming APIs.",
  "created_at": "2026-09-09T10:29:00.000Z",
  "updated_at": "2026-09-09T10:30:12.481Z",
  "archived_at": null,
  "active_run_id": null
}
```

Message:

```json
{
  "id": "uuid",
  "conversation_id": "uuid",
  "role": "user",
  "content": "Explain backpressure in streaming APIs.",
  "status": "complete",
  "client_message_id": "uuid",
  "in_reply_to_id": null,
  "version": 1,
  "is_visible": true,
  "created_at": "2026-09-09T10:30:00.000Z"
}
```

User messages always persist with `status: "complete"`. Assistant `status` is `partial`, `complete`, `cancelled`, or `failed`.

Run snapshot (`GET /v1/response-runs/{id}` and `POST .../cancel` only). Retry and regenerate do **not** return this JSON; they are `200 application/x-ndjson` like create-and-stream, start generation only on first accept of the idempotency key, and on key replay attach a follower to the existing new run:

```json
{
  "id": "uuid",
  "conversation_id": "uuid",
  "user_message_id": "uuid",
  "assistant_message_id": "uuid",
  "status": "streaming",
  "attempt": 1,
  "last_sequence": 17,
  "cancel_requested_at": null,
  "error_code": null,
  "diagnostic_id": null,
  "partial_content": "Backpressure is",
  "created_at": "2026-09-09T10:30:00.100Z",
  "completed_at": null
}
```

`GET /v1/conversations/{id}?cursor=&limit=` returns `{ "conversation": Conversation, "messages": PaginationEnvelope, "active_run": RunSnapshot | null }`. Message pages are **oldest-first** keyset on `(created_at, id)`, default `limit=50`, max `100`. Hidden answer versions (`is_visible=false`) **are included** so clients can render one live bubble and still paginate. `conversation.active_run_id` and `active_run` are derived from the non-terminal `response_runs` row; they are not stored on `conversations`.

Conversation list is **newest-first** on `(updated_at, id)`.

## 3. Create-and-stream request

```http
POST /v1/conversations/0195.../responses
Idempotency-Key: 0195f4d8-...
Content-Type: application/json
Accept: application/x-ndjson
```

```json
{
  "client_message_id": "0195f4d8-4ee0-7a35-8bc4-63cb5966b448",
  "content": "Explain backpressure in streaming APIs."
}
```

Rules:

- `content` is trimmed, non-empty, and capped at the configured request boundary.
- The tuple `(user_id, operation, idempotency_key)` is unique.
- Reusing a key with a different request fingerprint returns `409`.
- Reusing it with the same fingerprint attaches to the existing run and replays from sequence `0`.
- A second active run for the same conversation returns `409 conversation_busy` with extension members `conversation_id` and `active_run_id`. Clients must not automatically create another run; they follow that `active_run_id` (GET run, then POST stream). `too_many_active_runs` has no `active_run_id`.
- Empty or whitespace-only `content` after trim is `400 validation_failed`.
- `content` longer than `MAX_MESSAGE_CHARS` is `400 validation_failed`.
- Default title of a new conversation is the first user message trimmed and clipped to 80 characters; `PATCH` may rename afterward.

### Other mutating bodies

`POST /v1/conversations` with optional `{ "title": "..." }` creates an empty conversation. Omit `title` to use `"New conversation"` until the first user message arrives.

`PATCH /v1/conversations/{id}`:

```json
{ "title": "Backpressure", "archived": false }
```

At least one field is required. `title` is trimmed, non-empty, max 120 characters. `archived: true` sets `archived_at`; `archived: false` clears it (recoverable archive). Archived conversations remain readable and listable through `?include_archived=true` (default list excludes them). Sending a new response to an archived conversation is `409 conversation_archived`. Later user messages never overwrite a title that is no longer `"New conversation"`.

`POST /v1/response-runs/{id}/stream`:

```json
{ "after_sequence": 17 }
```

`after_sequence` is an integer `>= 0`. `0` replays from the beginning of retained events.

`POST /v1/response-runs/{id}/cancel` has body `{}`.

`POST /v1/response-runs/{id}/retry` has body `{}`. Allowed only when the source run is `failed` or `cancelled`. Any other source status is `409 invalid_run_state` (no `active_run_id`). If the conversation is archived: `409 conversation_archived`.

`POST /v1/messages/{user_message_id}/regenerations` has body `{}`. If the conversation already has a non-terminal run: `409 conversation_busy` with `active_run_id`. If there is no visible assistant for that user message: `409 invalid_run_state`. If archived: `409 conversation_archived`.

### Retry versus regenerate

| Source run | Retry | Regenerate |
|---|---|---|
| `failed` | New run, same user message, same visible assistant slot until the new run is accepted then the new assistant version becomes visible | Not the primary control; regenerate is also allowed |
| `cancelled` | Same as failed | Allowed |
| `completed` | Not allowed | New assistant version; previous remains stored with `is_visible=false` |
| `queued` / `streaming` / `cancelling` | `409 invalid_run_state` | `409 conversation_busy` |

Both create a new `response_runs` row **and** a new assistant message version because terminal assistant content is immutable. `attempt` on the new run is `previous.attempt + 1` for retry and `1` for a fresh regenerate of a completed answer (regenerate from failed/cancelled also increments `attempt`). The previous assistant row stays stored with `is_visible=false`.

## 4. Event envelope

Every physical line is one complete JSON object followed by `\n`:

```json
{
  "protocol_version": "1.0",
  "sequence": 3,
  "event_id": "0195f4db-2159-7d06-8895-1c0f36c7d8a4",
  "type": "message.delta",
  "occurred_at": "2026-09-09T10:30:12.481Z",
  "conversation_id": "0195f4d4-...",
  "run_id": "0195f4da-...",
  "data": {}
}
```

Invariants:

- Persisted events: `sequence` starts at `1`, increases by one within a run, and is the replay cursor. This applies to rows in `stream_events`.
- A persisted event becomes streamable only after its database transaction commits.
- `heartbeat` and `response.snapshot` are not `stream_events` rows. They reuse envelope `sequence` equal to the run's `last_sequence` and must not be treated as unknown types.
- Duplicate persisted events may be delivered after reconnect; consumers ignore persisted types when `sequence <= last_applied_sequence`. `response.snapshot` is applied even when its sequence equals the cursor if the client requested replay because of compaction/gap; after applying it, set `last_applied_sequence` to `data.last_sequence`.
- Unknown event types within major version `1` are ignored and logged.
- An unsupported major version stops parsing and triggers canonical reconciliation.
- Exactly one terminal event is committed per run.

## 5. V1 events

### `response.started`

```json
{"data":{"user_message_id":"uuid","assistant_message_id":"uuid","client_message_id":"uuid","attempt":1}}
```

Reconciles optimistic IDs and establishes the assistant placeholder.

### `message.delta`

```json
{"data":{"message_id":"uuid","delta":"Backpressure is","content_index":0}}
```

`content_index` is the Unicode **code-point** length of canonical content before this delta (Python `len(str)`; JavaScript `Array.from(content).length`, never `String.length`). A mismatched index causes the client to stop applying deltas and reconcile from the server. Fixtures and parser tests must include a supplementary-plane character (for example `👍`).

### `usage.updated`

```json
{"data":{"input_tokens":42,"output_tokens":18}}
```

Optional and monotonic; omitted when the provider cannot report interim usage.

### `heartbeat`

```json
{"data":{"last_sequence":17}}
```

Connection-only keepalive. It is **not** inserted into `stream_events`, does **not** increment `sequence`, and does **not** change chat state. The envelope `sequence` on a heartbeat equals `last_sequence` of the run (the latest committed event). Clients ignore heartbeats in the reducer. If the idle interval elapses with no committed event, the follower emits a heartbeat on the open HTTP connection.

### `response.snapshot`

```json
{
  "data": {
    "status": "streaming",
    "user_message_id": "uuid",
    "assistant_message_id": "uuid",
    "content": "canonical text so far",
    "last_sequence": 42
  }
}
```

Synthesized when `after_sequence` is below the retained event window, or when a follower attaches to a run whose early events were compacted. It is **not** a historical `stream_events` row. Envelope `sequence` equals `data.last_sequence`. The client **replaces** assistant content with `data.content`, sets `last_applied_sequence` to `last_sequence`, and then applies only later live events. `response.snapshot` may appear instead of `response.started` on replay.

### `message.completed`

```json
{"data":{"message_id":"uuid","content":"Backpressure is ...","finish_reason":"stop"}}
```

The full canonical content replaces client accumulation.

### `response.completed`

```json
{"data":{"finish_reason":"stop","usage":{"input_tokens":42,"output_tokens":91}}}
```

### `response.cancelled`

```json
{"data":{"reason":"user_requested","partial_content_retained":true,"content":"partial markdown"}}
```

### `response.failed`

```json
{"data":{"code":"provider_unavailable","message":"The assistant is temporarily unavailable.","retryable":true,"diagnostic_id":"uuid","content":"partial markdown"}}
```

The public message is safe to display; provider details remain only in protected logs.

### Finish reasons

`finish_reason` on `message.completed` / `response.completed` is `stop` or `length` only. Cancelled runs emit **only** `response.cancelled` (no `message.completed`); the client takes frozen text from `data.content` on that event (or GET run / conversation). Failed runs emit `response.failed` only, leaving assistant `status=failed` and retaining partial content.

## 6. Reserved compatible event names

`tool.started`, `tool.completed`, `tool.failed`, `citation.added`, and `status.updated` are reserved. V1 consumers must ignore them safely; V1 servers do not emit them.

## 7. Replay/follow request

```json
{"after_sequence":17}
```

The endpoint first replays committed events above the cursor, then follows newly committed events until the run reaches a terminal state or the HTTP connection ends. If old event rows were compacted, it emits a `response.snapshot` event containing canonical message text, status, and the current sequence before following live events.

## 8. Cancellation semantics

The browser does two independent actions:

1. Abort the local `fetch` immediately so rendering stops.
2. Send an idempotent cancel request with a fresh short-lived request signal.

`POST /cancel` returns the current run representation. Cancelling a terminal run is a successful no-op. The generation task observes `cancel_requested_at`, closes the provider stream, persists partial text, and commits `response.cancelled`.

`data.reason` on `response.cancelled` is `user_requested`. Timeouts and provider failures use `response.failed`, not cancelled.

## 9. Problem details

```json
{
  "type": "https://copilot.local/problems/conversation_busy",
  "title": "Conversation already has an active response",
  "status": 409,
  "code": "conversation_busy",
  "diagnostic_id": "uuid",
  "conversation_id": "uuid",
  "active_run_id": "uuid"
}
```

Stable client decisions use `status` and `code`, never human-readable text.

### Problem code catalog

| `code` | HTTP | Retryable | When |
|---|---:|---|---|
| `validation_failed` | 400 | No | Schema, UUID, empty content, limit |
| `unauthenticated` | 401 | No | Missing/invalid actor |
| `not_found` | 404 | No | Missing or not owned |
| `idempotency_key_conflict` | 409 | No | Same key, different fingerprint |
| `conversation_busy` | 409 | No | One active run already exists |
| `conversation_archived` | 409 | No | Mutating an archived conversation |
| `invalid_run_state` | 409 | No | Retry/regenerate/cancel precondition failed (cancel on terminal is *not* this; it is a success no-op) |
| `too_many_active_runs` | 409 | No | Per-user active-run cap |
| `payload_too_large` | 413 | No | Body exceeds configured bytes |
| `rate_limited` | 429 | Yes | Per-user admission; `Retry-After` seconds |
| `service_unavailable` | 503 | Yes | Database or dependency not ready |
| `internal_error` | 500 | Yes | Unexpected; `diagnostic_id` present |

Stream-terminal codes (on `response.failed`, not HTTP): `provider_unavailable`, `provider_rate_limited`, `provider_timeout`, `provider_protocol_error`, `output_limit_exceeded`, `server_restart`, `persistence_failed`, `cancelled_cleanup_failed`.

### Health

`GET /health/live` → `200 { "status": "live" }` if the process can answer HTTP.

`GET /health/ready` → `200 { "status": "ready", "database": "ok" }` when PostgreSQL accepts a trivial query; otherwise `503 { "status": "not_ready", "database": "error" }` as problem+json with `code=service_unavailable`.

### Degraded non-streaming clients

V1 does not add a separate complete-response endpoint. Browsers without `ReadableStream` poll `GET /v1/response-runs/{id}` until a terminal status, then read canonical messages from `GET /v1/conversations/{id}`.

### Rate-limit headers

On `429` and, when remaining quota is low, on mutating responses:

```http
Retry-After: 2
X-RateLimit-Limit: 20
X-RateLimit-Remaining: 0
X-RateLimit-Policy: user;w=60
```
