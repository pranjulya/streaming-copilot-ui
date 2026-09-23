import hashlib
import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from uuid import uuid4

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)
run_id_var: ContextVar[str | None] = ContextVar("run_id", default=None)


def new_request_id() -> str:
    return str(uuid4())


def new_trace_id() -> str:
    return uuid4().hex


def hash_user_id(user_id: str) -> str:
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:16]


class CorrelationFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        record.trace_id = trace_id_var.get()
        record.run_id = run_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in ("request_id", "trace_id", "run_id", "user_id_hash", "run_status"):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["error"] = record.exc_info[0].__name__ if record.exc_info[0] else "Error"
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(CorrelationFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


def log_span(logger: logging.Logger, name: str, **fields: object) -> None:
    """Structured span line; provider text and prompts are never passed here."""
    safe_fields = {key: value for key, value in fields.items()}
    logger.info("%s", name, extra=safe_fields)
