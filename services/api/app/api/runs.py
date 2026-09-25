from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import rfc3339
from app.api.auth import Actor, require_actor
from app.chat.responses import RunSnapshot, get_run, request_cancel
from app.persistence.session import get_session

router = APIRouter(prefix="/v1/response-runs", tags=["response-runs"])


def run_snapshot_dict(snapshot: RunSnapshot) -> dict[str, object]:
    run = snapshot.run
    return {
        "id": str(run.id),
        "conversation_id": str(run.conversation_id),
        "user_message_id": str(run.user_message_id),
        "assistant_message_id": str(run.assistant_message_id),
        "status": run.status,
        "attempt": run.attempt,
        "last_sequence": run.last_sequence,
        "cancel_requested_at": rfc3339(run.cancel_requested_at)
        if run.cancel_requested_at
        else None,
        "error_code": run.error_code,
        "diagnostic_id": run.diagnostic_id,
        "partial_content": snapshot.partial_content,
        "created_at": rfc3339(run.created_at),
        "completed_at": rfc3339(run.completed_at) if run.completed_at else None,
    }


@router.get("/{run_id}")
async def get_run_route(
    run_id: UUID,
    actor: Actor = Depends(require_actor),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    snapshot = await get_run(run_id, actor, session=session)
    return run_snapshot_dict(snapshot)


@router.post("/{run_id}/cancel")
async def cancel_run_route(
    run_id: UUID,
    actor: Actor = Depends(require_actor),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    snapshot = await request_cancel(run_id, actor, session=session)
    return run_snapshot_dict(snapshot)
