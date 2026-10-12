TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"streaming", "cancelling", "failed"}),
    "streaming": frozenset({"cancelling", "completed", "failed"}),
    "cancelling": frozenset({"cancelled", "failed"}),
    "completed": frozenset(),
    "cancelled": frozenset(),
    "failed": frozenset(),
}

# The single vocabulary for run statuses. The ordered tuples are the source of
# truth so that SQL built from them stays deterministic; the frozensets are for
# membership tests.
ACTIVE_STATUS_ORDER: tuple[str, ...] = ("queued", "streaming", "cancelling")
TERMINAL_STATUS_ORDER: tuple[str, ...] = ("completed", "cancelled", "failed")

ACTIVE_STATUSES = frozenset(ACTIVE_STATUS_ORDER)
TERMINAL_STATUSES = frozenset(TERMINAL_STATUS_ORDER)


class InvalidStateTransition(Exception):
    def __init__(self, current: str, target: str) -> None:
        super().__init__(f"cannot transition run from {current!r} to {target!r}")
        self.current = current
        self.target = target


def is_terminal(status: str) -> bool:
    return status in TERMINAL_STATUSES


def assert_transition(current: str, target: str) -> None:
    allowed = TRANSITIONS.get(current)
    if allowed is None:
        raise InvalidStateTransition(current, target)
    if target not in allowed:
        raise InvalidStateTransition(current, target)
