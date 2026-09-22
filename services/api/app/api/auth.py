from dataclasses import dataclass

from fastapi import Request

from app.api.errors import AppError
from app.settings import Settings


@dataclass(frozen=True)
class Actor:
    user_id: str


def require_actor(request: Request) -> Actor:
    settings: Settings = request.app.state.settings
    header = request.headers.get("x-dev-user")
    if settings.app_env == "development":
        candidate = header.strip() if header is not None else ""
        if candidate:
            return Actor(user_id=candidate)
        return Actor(user_id=settings.dev_user_id or "dev-user")
    raise AppError(401, "unauthenticated", "Authentication required")
