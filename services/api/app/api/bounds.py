from fastapi import Request

from app.api.errors import AppError
from app.api.rate_limit import UserRateLimiter
from app.settings import Settings


def limiter_for(request: Request) -> UserRateLimiter:
    limiter: UserRateLimiter | None = getattr(request.app.state, "rate_limiter", None)
    if limiter is None:
        settings: Settings = request.app.state.settings
        limiter = UserRateLimiter(settings.create_response_per_minute)
        request.app.state.rate_limiter = limiter
    return limiter


def enforce_send_rate(request: Request, user_id: str) -> None:
    settings: Settings = request.app.state.settings
    limiter = limiter_for(request)
    allowed, retry_after = limiter.check(user_id)
    if allowed:
        return
    raise AppError(
        429,
        "rate_limited",
        "Too many responses requested; try again shortly",
        headers={
            "Retry-After": str(retry_after),
            "X-RateLimit-Limit": str(settings.create_response_per_minute),
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Policy": "user;w=60",
        },
    )


def enforce_body_bound(request: Request, raw_body: bytes) -> None:
    settings: Settings = request.app.state.settings
    if len(raw_body) > settings.max_request_bytes:
        raise AppError(413, "payload_too_large", "Request body is too large")
