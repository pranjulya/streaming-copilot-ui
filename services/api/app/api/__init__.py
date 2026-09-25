"""HTTP routes."""

from datetime import UTC, datetime


def rfc3339(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
