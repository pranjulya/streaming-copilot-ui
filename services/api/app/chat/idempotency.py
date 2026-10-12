"""The idempotency-record lookup shared by every mutating command.

The rule is the same everywhere (`docs/api-and-stream-contracts.md` §1, ADR-007):
a record replays the resource it points at, a request whose body hash differs is
a conflict, and an expired record is dropped so its key becomes usable again.

Run-creating commands add one refinement: an expired record is still honoured
while the run it points at is active, so a retry during a live generation replays
that run instead of starting a second one. Callers express that with `still_live`
rather than growing a second copy of this logic.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.chat.state_machine import ACTIVE_STATUSES
from app.observability.metrics import IDEMPOTENCY_HITS_TOTAL
from app.persistence.models import IdempotencyRecord, ResponseRun

# True when an already-expired record must still be honoured.
StillLive = Callable[[IdempotencyRecord, AsyncSession], Awaitable[bool]]


async def run_still_active(record: IdempotencyRecord, session: AsyncSession) -> bool:
    """An expired record still replays while the run it points at is active."""
    run = await session.get(ResponseRun, record.resource_id)
    return run is not None and run.status in ACTIVE_STATUSES


async def find_record(
    session: AsyncSession,
    *,
    user_id: str,
    operation: str,
    key: UUID,
    request_hash: str,
    still_live: StillLive | None = None,
) -> IdempotencyRecord | None:
    record = await session.get(IdempotencyRecord, (user_id, operation, key))
    if record is None:
        return None
    if record.expires_at <= datetime.now(UTC) and not (
        still_live is not None and await still_live(record, session)
    ):
        await session.delete(record)
        # Flush the delete now: a caller may re-insert the same primary key in
        # this transaction, and the unit of work would otherwise order the
        # INSERT before the DELETE.
        await session.flush()
        return None
    if record.request_hash != request_hash:
        IDEMPOTENCY_HITS_TOTAL.labels(operation=operation, result="conflict").inc()
        raise AppError(
            409,
            "idempotency_key_conflict",
            "Idempotency-Key was already used with a different request",
        )
    return record
