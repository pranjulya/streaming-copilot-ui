import json
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import Actor, require_actor
from app.api.errors import AppError
from app.persistence.session import get_session
from app.providers.protocol import LlmProvider

router = APIRouter(prefix="/v1/_test", tags=["dev"])


def _plan_provider(steps: list[dict[str, Any]]) -> LlmProvider:
    from app.providers.fake import FakeProvider, PlannedFakeProvider

    return PlannedFakeProvider(
        [
            FakeProvider(
                deltas=step.get("deltas", []),
                finish_reason=step.get("finish_reason", "stop"),
                fail_after=step.get("fail_after"),
                delay_seconds=float(step.get("delay_seconds", 0.0)),
                ignores_cancel=bool(step.get("ignores_cancel", False)),
            )
            for step in steps
        ]
    )


@router.post("/fake-plan")
async def set_fake_plan(
    request: Request,
    actor: Actor = Depends(require_actor),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    del actor, session
    settings = request.app.state.settings
    if settings.app_env != "development":
        raise AppError(404, "not_found", "Not found")
    raw = await request.body()
    try:
        body = json.loads(raw) if raw.strip() else {}
    except ValueError:
        raise AppError(400, "validation_failed", "Body must be valid JSON") from None
    steps = body.get("steps") if isinstance(body, dict) else None
    if not isinstance(steps, list) or not steps:
        raise AppError(400, "validation_failed", "steps must be a non-empty list")
    request.app.state.supervisor.set_provider(_plan_provider(steps))
    return {"status": "planned", "steps": len(steps)}
