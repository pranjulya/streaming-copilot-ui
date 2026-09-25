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


RATE_LIMIT_POLICY = "user;w=60"


def rate_limit_headers(settings: Settings, remaining: int) -> dict[str, str]:
    return {
        "X-RateLimit-Limit": str(settings.create_response_per_minute),
        "X-RateLimit-Remaining": str(max(0, remaining)),
        "X-RateLimit-Policy": RATE_LIMIT_POLICY,
    }


def enforce_send_rate(request: Request, user_id: str) -> int:
    """Consume one send from the caller's window and return the remaining quota."""
    settings: Settings = request.app.state.settings
    limiter = limiter_for(request)
    allowed, retry_after = limiter.check(user_id)
    if not allowed:
        raise AppError(
            429,
            "rate_limited",
            "Too many responses requested; try again shortly",
            headers={"Retry-After": str(retry_after), **rate_limit_headers(settings, 0)},
        )
    remaining = limiter.remaining(user_id)
    request.state.rate_limit_remaining = remaining
    return remaining


def low_quota_rate_limit_headers(request: Request) -> dict[str, str]:
    """Rate-limit headers for a successful mutating response only when quota runs low."""
    remaining = getattr(request.state, "rate_limit_remaining", None)
    if remaining is None:
        return {}
    settings: Settings = request.app.state.settings
    low_watermark = max(1, settings.create_response_per_minute // 5)
    if remaining > low_watermark:
        return {}
    return rate_limit_headers(settings, remaining)


def enforce_body_bound(request: Request, raw_body: bytes) -> None:
    settings: Settings = request.app.state.settings
    if len(raw_body) > settings.max_request_bytes:
        raise AppError(413, "payload_too_large", "Request body is too large")
