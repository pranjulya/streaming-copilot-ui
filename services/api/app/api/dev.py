import json

from fastapi import APIRouter, Depends, Request

from app.api.auth import Actor, require_actor
from app.api.bounds import enforce_body_bound
from app.api.errors import AppError
from app.providers.fake import planned_provider_from_steps

router = APIRouter(prefix="/v1/_test", tags=["dev"])


@router.post("/fake-plan")
async def set_fake_plan(
    request: Request,
    actor: Actor = Depends(require_actor),
) -> dict[str, object]:
    del actor
    settings = request.app.state.settings
    if settings.app_env != "development":
        raise AppError(404, "not_found", "Not found")
    raw = await request.body()
    enforce_body_bound(request, raw)
    try:
        body = json.loads(raw) if raw.strip() else {}
    except ValueError:
        raise AppError(400, "validation_failed", "Body must be valid JSON") from None
    steps = body.get("steps") if isinstance(body, dict) else None
    if not isinstance(steps, list) or not steps:
        raise AppError(400, "validation_failed", "steps must be a non-empty list")
    request.app.state.supervisor.set_provider(planned_provider_from_steps(steps))
    return {"status": "planned", "steps": len(steps)}
