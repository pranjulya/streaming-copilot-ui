# Observability

## 1. Objectives

Operators must answer: Is chat available? Where is latency? Which failure class dominates? Did cancellation work? Did persistence match the stream? Which user-visible incident corresponds to a diagnostic ID?

## 2. Correlation fields

Every backend log/event includes where available:

- `trace_id`, `request_id`, `diagnostic_id`
- `user_id_hash` (never raw identity)
- `conversation_id`, `run_id`, `message_id`
- `idempotency_key_hash`
- `provider`, `model`, `event_type`, `sequence`
- `run_status`, `error_code`, `http_status`

The browser records request/run IDs and coarse event metadata, never prompt or response text.

## 3. Metrics

### Traffic and correctness

- Requests and response runs by endpoint/status/model
- Active and orphaned runs
- Idempotency hits and mismatched-key conflicts
- NDJSON events and bytes emitted
- Sequence-gap, duplicate-event, and reconciliation counts
- Stream/database final-content mismatch count

### Latency

- API accept latency
- Provider connect and first-token latency
- Service overhead to first event
- Inter-event gap and total generation duration
- Cancellation request-to-terminal latency
- Reconnect-to-caught-up latency
- Database transaction/query latency

### Resource/cost signals

- Input/output tokens
- Event rows and bytes per run
- Open stream count and duration
- Database pool saturation
- Provider throttling and timeout rates

Use histograms for latency/size, counters for outcomes, and gauges only for current state.

Canonical metric names (Units in braces):

| Name | Type | Labels |
|---|---|---|
| `copilot_http_requests_total` | counter | `endpoint`, `status`, `code` |
| `copilot_runs_terminal_total` | counter | `status`, `error_code`, `model` |
| `copilot_runs_active` | gauge | `model` |
| `copilot_runs_orphaned_total` | counter | — |
| `copilot_idempotency_hits_total` | counter | `operation`, `result` |
| `copilot_events_emitted_total` | counter | `type` |
| `copilot_stream_bytes_total` | counter | — |
| `copilot_sequence_gaps_total` | counter | — |
| `copilot_content_mismatch_total` | counter | — |
| `copilot_accept_latency_seconds` | histogram | `endpoint` |
| `copilot_provider_first_token_seconds` | histogram | `model` |
| `copilot_service_first_event_seconds` | histogram | `model` |
| `copilot_generation_duration_seconds` | histogram | `model` |
| `copilot_cancel_ack_seconds` | histogram | — |
| `copilot_reconnect_catchup_seconds` | histogram | — |
| `copilot_db_tx_seconds` | histogram | `op` |
| `copilot_tokens_total` | counter | `direction`, `model` |

## 4. Traces

One trace spans HTTP acceptance, ownership/idempotency transaction, supervisor start, provider request, event commits, and terminal transition. Long-lived event-follow reads may use linked spans to avoid one unbounded trace. Provider text and full prompts are excluded from span attributes.

## 5. Structured logs

Log lifecycle milestones, not each token. Delta logging is sampled metadata only: sequence, byte count, and duration. Log levels:

- `INFO`: accepted, started, terminal, cancel requested, replay attached.
- `WARN`: retryable provider error, slow consumer, sequence recovery, orphan recovery.
- `ERROR`: invariant violation, persistence failure, unrecoverable protocol error.

## 6. Dashboards and alerts

Dashboard panels cover availability, terminal outcomes, time to first event, total duration, provider errors, active streams, database health, retry/reconnect, cancellation, and token volume.

Page only on user-impacting signals: sustained acceptance failure, durable terminal-state deficit, database readiness loss, high orphan rate, or severe first-event regression. Ticket-level alerts cover event-store growth, rising retries, and provider-specific degradation.

## 7. Privacy and retention

No content in ordinary logs, metrics, or traces. Diagnostic content capture is off by default and requires a separately secured, time-bounded process. Stream events follow product retention; operational telemetry follows a shorter policy. When a future deletion phase exists, it must cover conversations/messages/events and derived diagnostic stores. V1 has archive only.

## 8. Frontend telemetry

Capture page/session ID, browser capability, request/run correlation IDs, coarse state transitions, time-to-first-rendered-delta, parse failures, gaps, reconnect attempts, and terminal outcome. Respect consent and privacy policy; do not capture composer or transcript contents.
