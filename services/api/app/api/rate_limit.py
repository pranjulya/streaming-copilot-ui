import time
from collections import defaultdict, deque


class UserRateLimiter:
    """Best-effort per-user sliding window in process memory.

    V1 has no cluster-wide counter: N replicas multiply the effective quota.
    """

    def __init__(self, per_minute: int, window_seconds: float = 60.0) -> None:
        self._per_minute = per_minute
        self._window = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def check(self, user_id: str) -> tuple[bool, int]:
        """Returns (allowed, retry_after_seconds)."""
        now = time.monotonic()
        bucket = self._events[user_id]
        cutoff = now - self._window
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= self._per_minute:
            retry_after = max(1, int(self._window - (now - bucket[0])) + 1)
            return False, retry_after
        bucket.append(now)
        return True, 0

    def remaining(self, user_id: str) -> int:
        return max(0, self._per_minute - len(self._events[user_id]))
