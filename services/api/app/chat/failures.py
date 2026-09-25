"""Public stream-terminal failure codes and the copy clients see.

The catalog is the single definition for the codes listed in
`docs/api-and-stream-contracts.md`: providers raise a code, and the supervisor
and orphan reaper turn it into a `response.failed` event. Messages never carry
exception text.
"""

from dataclasses import dataclass

from app.chat.event_writer import SafeFailure


@dataclass(frozen=True)
class FailureSpec:
    message: str
    retryable: bool = True


DEFAULT_FAILURE = FailureSpec(message="The assistant could not finish this response.")

FAILURES: dict[str, FailureSpec] = {
    "server_restart": FailureSpec(message="The assistant stopped responding. Retrying is safe."),
    "provider_unavailable": FailureSpec(message="The assistant is temporarily unavailable."),
    "provider_rate_limited": FailureSpec(
        message="The assistant is rate limited right now. Retrying is safe."
    ),
    "provider_timeout": FailureSpec(
        message="The assistant took too long to respond. Retrying is safe."
    ),
    "provider_protocol_error": FailureSpec(
        message="The assistant returned an unexpected response. Retrying is safe."
    ),
    "output_limit_exceeded": FailureSpec(
        message="The answer reached the length limit.", retryable=False
    ),
    "persistence_failed": FailureSpec(message="The response could not be saved. Retrying is safe."),
    "cancelled_cleanup_failed": FailureSpec(
        message="The cancellation did not finish cleanly. Retrying is safe."
    ),
}


def safe_failure(code: str) -> SafeFailure:
    spec = FAILURES.get(code, DEFAULT_FAILURE)
    return SafeFailure(code=code, message=spec.message, retryable=spec.retryable)
