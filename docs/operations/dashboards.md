# Dashboard queries (Phase 08)

Text-only queries over the metric name table in `docs/observability.md` §3. They
contain no user content and no prompt/response text.

## Availability

```promql
# Request failure ratio (5m)
sum(rate(copilot_http_requests_total{status=~"5.."}[5m]))
  / sum(rate(copilot_http_requests_total[5m]))

# Readiness (scrape /health/ready from the private network)
probe_success{job="copilot-api-ready"}
```

## Terminal outcomes and orphan recovery

```promql
sum by (status, error_code) (rate(copilot_runs_terminal_total[15m]))

# High orphan rate pages: restarts or crash loops
sum(rate(copilot_runs_orphaned_total[15m])) > 0.1
```

## Latency (PRD SLOs)

```promql
histogram_quantile(0.95, sum by (le) (rate(copilot_accept_latency_seconds_bucket[5m])))
histogram_quantile(0.95, sum by (le) (rate(copilot_service_first_event_seconds_bucket[5m])))
histogram_quantile(0.95, sum by (le) (rate(copilot_generation_duration_seconds_bucket[5m])))
histogram_quantile(0.95, sum by (le) (rate(copilot_cancel_ack_seconds_bucket[5m])))
histogram_quantile(0.95, sum by (le) (rate(copilot_reconnect_catchup_seconds_bucket[5m])))
```

## Provider health and cost

```promql
sum by (code) (rate(copilot_http_requests_total{endpoint="/v1/conversations/{conversation_id}/responses"}[5m]))

sum by (direction) (rate(copilot_tokens_total[1h]))

# Streaming volume and reconnection pressure
sum(rate(copilot_events_emitted_total[5m]))
sum(rate(copilot_stream_bytes_total[5m]))
```

## Correctness

```promql
# Must stay zero: streamed terminal content disagreed with storage
increase(copilot_content_mismatch_total[1h]) > 0

# Sequence gaps observed by followers
increase(copilot_sequence_gaps_total[1h]) > 0

# Idempotency behaviour
sum by (result) (rate(copilot_idempotency_hits_total[1h]))
```

## Alert routing

Page on: sustained acceptance failures, readiness loss, any `content_mismatch`
increase, orphan-rate spikes, first-event p95 regression beyond the PRD bar.
Ticket on: event-store growth, rising retry/pagination usage, provider-specific
error increases.
