"""Trace identifiers and span logs. Provider text is never passed here."""

from collections.abc import Iterator
from contextlib import contextmanager
from logging import Logger
from uuid import UUID

from app.observability.logging import log_span, run_id_var


def bind_run(run_id: UUID) -> None:
    run_id_var.set(str(run_id))


@contextmanager
def generation_span(logger: Logger, run_id: UUID) -> Iterator[None]:
    bind_run(run_id)
    log_span(logger, "generation.start", run_id=str(run_id))
    try:
        yield
        log_span(logger, "generation.ok", run_id=str(run_id))
    except Exception:
        log_span(logger, "generation.error", run_id=str(run_id))
        raise
