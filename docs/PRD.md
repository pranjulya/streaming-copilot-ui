# Product Requirements Document

## 1. Product summary

Project 6 is a browser-based, full-chat Copilot. A signed-in user can create and revisit conversations, send a message, watch the assistant response arrive incrementally, stop generation, retry failures, regenerate an answer, and recover cleanly from refreshes or network interruptions.

The product is a learning-focused production reference: it must expose the real engineering concerns of streaming chat without adding infrastructure that V1 does not need.

## 2. Goals

1. Deliver a responsive chat experience with first visible assistant output after the backend receives provider output.
2. Persist canonical conversation and message history on the server.
3. Make every response lifecycle explicit through typed, versioned NDJSON events.
4. Keep optimistic client state reconcilable with server state after success, retry, cancellation, refresh, or ambiguous network failure.
5. Provide enough security, observability, tests, and operational behavior to run the system responsibly in production.
6. Teach the architecture in an incremental, phase-based implementation path.

## 3. Non-goals for V1

- Multi-user collaborative conversations
- Conversation branching UI
- Voice, image, or file input
- Offline message composition or background sync
- A general agent/tool framework or user-configurable tools
- Exposed chain-of-thought
- WebSocket or SSE transport
- Cross-region active-active generation
- Semantic search, RAG, or vector storage
- Billing and organization administration

The event envelope reserves tool and citation event names so the protocol can evolve, but V1 does not execute tools or retrieve citations.

## 4. Users and jobs

### Primary user

A signed-in learner or knowledge worker using the Copilot from a modern desktop or mobile browser.

### Jobs to be done

- Start a new conversation and get a streamed answer.
- Continue an existing conversation with enough recent context for coherent replies.
- Understand whether the assistant is connecting, generating, completed, stopped, or failed.
- Stop a costly or unwanted response.
- Recover without duplicated user messages or competing assistant answers.
- Return later and see the canonical conversation history.

## 5. Functional requirements

### Conversation history

- Create, list, read, rename, and archive conversations owned by the current user.
- Paginate conversations and messages with opaque cursors.
- Persist messages in stable chronological order.
- Default a new title from the first user message; allow later rename.

### Sending and streaming

- Accept one user turn through a streaming `POST` request.
- Render the user message optimistically with a client-generated UUID.
- Stream newline-delimited JSON records and parse records split across arbitrary network chunks.
- Display assistant deltas as they arrive.
- Reconcile optimistic IDs and accumulated text with canonical server IDs and final content.
- Ignore unknown event types from newer compatible protocol versions while recording a diagnostic.

### Lifecycle controls

- Cancel the local read immediately through `AbortController` and request canonical server cancellation separately.
- Retry a failed or interrupted run without duplicating the user message.
- Regenerate an answer as a new response run for the same user message, retaining prior versions for audit while showing one active version.
- Restore a conversation after refresh and reconcile any run whose outcome was unknown to the browser.

### Errors and degradation

- Distinguish validation, authentication, authorization, rate-limit, provider, timeout, protocol, network, and server errors.
- Preserve the user message and any canonical partial assistant content when a response fails.
- Fall back to canonical history plus retry when live resumption is unavailable.
- Keep navigation and existing history usable when generation is unavailable.

## 6. UX requirements

- A conversation list, active transcript, composer, send/stop control, per-response retry/regenerate actions, and clear status text.
- Keyboard submit with an accessible alternative; multiline entry remains possible.
- Streaming updates are visually smooth and do not move focus.
- Status changes are available to assistive technology without announcing every token.
- Destructive archive actions require a recoverable path: archive is a confirmed `PATCH archived: true` and is reversed with `archived: false`. V1 has no hard-delete UI.
- Reduced-motion preferences are respected.

## 7. Success measures

Measured at the service boundary and segmented by provider/model:

- At least 99% of accepted turns end in a durable terminal run state.
- No duplicate canonical user message for repeated requests with the same user, conversation, and idempotency key.
- p95 time-to-first-event under 1 second excluding provider first-token latency.
- p95 cancellation acknowledgement under 2 seconds while the provider is yielding data.
- At least 99.9% of completed runs have matching final assistant content in the event stream and database.
- Zero cross-user conversation access in authorization tests.
- The contract fixture suite passes for every supported event type.

These are initial service objectives, not traffic forecasts. Revise them only with measured production data.

## 8. Constraints and assumptions

- Modern browsers with `fetch`, `ReadableStream`, `TextDecoder`, and `AbortController`.
- Authentication is supplied by the host product; this project defines its boundary and a local development identity, not a new identity provider.
- PostgreSQL is the only required stateful dependency in V1.
- One active response run per conversation.
- Responses are text-only Markdown rendered through a sanitizing renderer.
- Provider credentials remain server-side.
- The API and web app may deploy separately, but use a same-site origin in the preferred production topology.

## 9. Acceptance journey

1. The user opens the app and sees persisted conversations.
2. The user starts a conversation and sends “Explain backpressure in streaming APIs.”
3. The optimistic user message appears immediately and is later reconciled to a server ID.
4. The assistant placeholder transitions from connecting to streaming, then accumulates typed deltas.
5. A refresh during generation restores canonical history and either reconnects to the active run or presents a precise retry state.
6. Stop ends both local rendering and server generation; the partial answer remains labeled stopped.
7. Regenerate creates another answer version without another user message.
8. Returning in a later session restores the same conversation.

## 10. Release gate

V1 is releasable only when the end-to-end journey, ownership isolation, idempotency, cancel/retry behavior, migration rollback rehearsal, load target, dashboards, and operational runbook have passed their phase acceptance checks.
