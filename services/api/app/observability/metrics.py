from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

REGISTRY = CollectorRegistry()


def _counter(name: str, documentation: str, labels: tuple[str, ...] = ()) -> Counter:
    return Counter(name, documentation, labels, registry=REGISTRY)


def _histogram(name: str, documentation: str, labels: tuple[str, ...] = ()) -> Histogram:
    return Histogram(name, documentation, labels, registry=REGISTRY)


HTTP_REQUESTS_TOTAL = _counter(
    "copilot_http_requests_total",
    "HTTP requests by endpoint, status and stable code",
    ("endpoint", "status", "code"),
)
RUNS_TERMINAL_TOTAL = _counter(
    "copilot_runs_terminal_total",
    "Terminal response runs by status and error code",
    ("status", "error_code", "model"),
)
RUNS_ACTIVE = Gauge(
    "copilot_runs_active",
    "Currently active (non-terminal) runs known to this process",
    ("model",),
    registry=REGISTRY,
)
RUNS_ORPHANED_TOTAL = _counter(
    "copilot_runs_orphaned_total", "Runs failed by orphan or lease recovery"
)
IDEMPOTENCY_HITS_TOTAL = _counter(
    "copilot_idempotency_hits_total",
    "Idempotency key replays and conflicts",
    ("operation", "result"),
)
EVENTS_EMITTED_TOTAL = _counter(
    "copilot_events_emitted_total", "Stream events committed", ("type",)
)
STREAM_BYTES_TOTAL = _counter("copilot_stream_bytes_total", "NDJSON bytes emitted to clients")
SEQUENCE_GAPS_TOTAL = _counter("copilot_sequence_gaps_total", "Detected sequence gaps")
CONTENT_MISMATCH_TOTAL = _counter(
    "copilot_content_mismatch_total",
    "Stream final content that disagreed with canonical storage",
)
ACCEPT_LATENCY_SECONDS = _histogram(
    "copilot_accept_latency_seconds", "API accept latency", ("endpoint",)
)
PROVIDER_FIRST_TOKEN_SECONDS = _histogram(
    "copilot_provider_first_token_seconds", "Provider first-token latency", ("model",)
)
SERVICE_FIRST_EVENT_SECONDS = _histogram(
    "copilot_service_first_event_seconds", "Service overhead to first event", ("model",)
)
GENERATION_DURATION_SECONDS = _histogram(
    "copilot_generation_duration_seconds", "Total generation duration", ("model",)
)
CANCEL_ACK_SECONDS = _histogram(
    "copilot_cancel_ack_seconds", "Cancellation request to terminal latency"
)
RECONNECT_CATCHUP_SECONDS = _histogram(
    "copilot_reconnect_catchup_seconds", "Reconnect to caught-up latency"
)
DB_TX_SECONDS = _histogram("copilot_db_tx_seconds", "Database transaction latency", ("op",))
TOKENS_TOTAL = _counter(
    "copilot_tokens_total", "Provider tokens by direction", ("direction", "model")
)


def render_metrics() -> bytes:
    return generate_latest(REGISTRY)


METRICS_CONTENT_TYPE = CONTENT_TYPE_LATEST
