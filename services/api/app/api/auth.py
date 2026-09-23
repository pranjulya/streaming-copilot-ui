import logging
from dataclasses import dataclass

from fastapi import Request

from app.settings import Settings


@dataclass(frozen=True)
class Actor:
    user_id: str
    auth_mode: str = "development"


def _log_actor_resolved(user_id: str) -> None:
    from app.observability.logging import hash_user_id

    logging.getLogger("app.auth").info(
        "actor_resolved", extra={"user_id_hash": hash_user_id(user_id)}
    )


def require_actor(request: Request) -> Actor:
    settings: Settings = request.app.state.settings
    header = request.headers.get("x-dev-user")
    if settings.app_env == "development":
        candidate = header.strip() if header is not None else ""
        if candidate:
            _log_actor_resolved(candidate)
            return Actor(user_id=candidate)
        user_id = settings.dev_user_id or "dev-user"
        _log_actor_resolved(user_id)
        return Actor(user_id=user_id)
    from app.api.auth_jwt import authenticate

    user_id, mode = authenticate(request, settings)
    _log_actor_resolved(user_id)
    return Actor(user_id=user_id, auth_mode=mode)
