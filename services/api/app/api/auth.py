from dataclasses import dataclass

from fastapi import Request

from app.settings import Settings


@dataclass(frozen=True)
class Actor:
    user_id: str
    auth_mode: str = "development"


def require_actor(request: Request) -> Actor:
    settings: Settings = request.app.state.settings
    header = request.headers.get("x-dev-user")
    if settings.app_env == "development":
        candidate = header.strip() if header is not None else ""
        if candidate:
            return Actor(user_id=candidate)
        return Actor(user_id=settings.dev_user_id or "dev-user")
    from app.api.auth_jwt import authenticate

    user_id, mode = authenticate(request, settings)
    return Actor(user_id=user_id, auth_mode=mode)
