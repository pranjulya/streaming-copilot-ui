# High-Level Design

## 1. Recommended architecture

Use a modular monolith split into three deployable concerns:

1. **Next.js web app** — presentation, local chat state, NDJSON parsing, optimistic updates, and lifecycle controls.
2. **FastAPI service** — authentication boundary, conversation API, response orchestration, provider streaming, persistence, and NDJSON emission.
3. **PostgreSQL** — canonical conversations, messages, response runs, idempotency records, and replayable stream events.

The backend starts provider generation in a supervised in-process task. The HTTP response follows durable events written by that task. This separates generation lifetime from a single browser connection, allowing the same run to be replayed after a transient disconnect without Redis or a job queue. On process loss, startup recovery marks orphaned runs failed; users can retry safely.

## 2. Why this shape

- A raw request-owned generator is shorter but cannot reliably reconnect once the socket disappears.
- Redis plus a worker queue improves failover, but adds two operational systems before traffic proves the need.
- WebSockets add connection management without improving the one-request/one-stream interaction.
- PostgreSQL event replay is deliberately boring: one database already holds canonical chat state and can carry V1 throughput.

Upgrade to a durable queue and pub/sub only when measured write volume, multi-region requirements, or process-restart continuation exceed this design.

## 3. Component boundaries

### Web

- **Chat shell:** navigation, transcript, composer, responsive layout.
- **Conversation client:** typed HTTP operations and idempotency headers.
- **Stream decoder:** bytes → UTF-8 text → complete lines → validated event envelopes.
- **Chat reducer:** deterministic optimistic and server-event transitions.
- **Recovery coordinator:** reload canonical state, resume by cursor, or offer retry.

### API

- **Routes:** validate transport input and map domain errors to HTTP/problem details.
- **Conversation service:** ownership, history, naming, archiving.
- **Response service:** idempotent run creation, one-active-run rule, cancellation, retry, regeneration.
- **Generation supervisor:** owns in-process tasks and shutdown behavior.
- **Provider adapter:** converts provider-native chunks into provider-neutral deltas and terminal metadata.
- **Event store:** allocates per-run sequence numbers and commits events with message/run state.
- **Repositories:** narrow persistence operations over PostgreSQL.

### Database

- Canonical history and response status.
- Unique constraints enforce ownership-local idempotency and one visible response version.
- Stream events provide replay from an event sequence cursor.

## 4. Primary data flow

1. Web generates `client_message_id` and `Idempotency-Key`, then renders the user message optimistically.
2. `POST /v1/conversations/{conversation_id}/responses` validates ownership and atomically creates or finds the user message and response run.
3. API returns an NDJSON response and starts generation only when this idempotency record has no existing run.
4. The generation task writes each canonical event and related state transition transactionally.
5. The connected stream follows committed events and emits one JSON record per line.
6. The reducer maps canonical IDs, appends deltas by sequence, and replaces accumulated text with final canonical content on completion.
7. If connectivity is lost, the client reads run status and resumes after its last committed sequence.

## 5. Deployment topology

- CDN/edge serves Next.js static assets and forwards application traffic.
- Next.js and FastAPI share a site boundary; the API remains independently scalable.
- A managed PostgreSQL instance is the only mandatory state service.
- Multiple API replicas are safe because authoritative state and event cursors live in PostgreSQL. A run continues only on the replica holding a live owner lease; another replica may serve replay and cancellation requests. NULL or expired leases are recovered as `failed/server_restart` on a timer. Same-instance non-terminal rows are recovered only at startup, not by the periodic reaper (which would otherwise fail healthy local runs the supervisor is renewing).
- Graceful shutdown stops accepting new runs, gives active tasks a bounded drain window, then marks unfinished runs recoverable as failed.

## 6. Scaling thresholds

Keep the V1 design until evidence shows one of these conditions:

- Stream-event writes materially affect primary database latency.
- Runs must survive API process or host loss rather than fail and retry.
- Cross-region generation must continue through regional failure.
- Cancellation latency across replicas exceeds the objective.
- Tool execution needs independent workers, isolation, or long-running jobs.

At that point, preserve HTTP and event contracts while moving generation supervision and event distribution to a durable queue/pub-sub subsystem.

## 7. Explicitly deferred capabilities

Tools, citations, attachments, RAG, branching, shared conversations, and multimodal events are protocol-compatible extensions, not V1 implementation work.
