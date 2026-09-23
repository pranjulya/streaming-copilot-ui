import hashlib
from collections.abc import Callable
from typing import Any

import jwt
from fastapi import Request

from app.api.errors import AppError
from app.settings import Settings


class JwtVerifier:
    """Validates host-product JWTs (issuer, audience, signature, expiry, subject)."""

    def __init__(
        self, settings: Settings, key_resolver: Callable[[str], Any] | None = None
    ) -> None:
        self._settings = settings
        self._key_resolver = key_resolver
        self._jwks_client: jwt.PyJWKClient | None = None

    def _resolve_key(self, token: str) -> Any:
        if self._key_resolver is not None:
            return self._key_resolver(token)
        if self._jwks_client is None:
            url = self._settings.auth_jwt_jwks_url
            assert url is not None
            self._jwks_client = jwt.PyJWKClient(url, cache_keys=True)
        return self._jwks_client.get_signing_key_from_jwt(token).key

    def actor_user_id(self, token: str) -> str:
        settings = self._settings
        try:
            claims = jwt.decode(
                token,
                self._resolve_key(token),
                algorithms=["RS256", "ES256"],
                issuer=settings.auth_jwt_issuer,
                audience=settings.auth_jwt_audience,
                options={"require": ["exp", "iss", "aud"]},
            )
        except jwt.PyJWTError:
            raise AppError(401, "unauthenticated", "Authentication required") from None
        subject = claims.get(settings.auth_jwt_subject_claim)
        if not isinstance(subject, str) or not subject.strip():
            raise AppError(401, "unauthenticated", "Authentication required")
        return subject.strip()


def hash_user_id(user_id: str) -> str:
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:16]


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if header is None:
        return None
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _cookie_authenticated_mutation(request: Request, cookie_name: str) -> bool:
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return False
    return True


def authenticate(request: Request, settings: Settings) -> tuple[str, str]:
    """Returns (user_id, auth_mode) where auth_mode is bearer or cookie."""
    verifier: JwtVerifier = request.app.state.jwt_verifier
    token = _bearer_token(request)
    if token is not None:
        return verifier.actor_user_id(token), "bearer"
    cookie_name = settings.auth_cookie_name
    if cookie_name:
        cookie_token = request.cookies.get(cookie_name)
        if cookie_token:
            user_id = verifier.actor_user_id(cookie_token)
            if _cookie_authenticated_mutation(request, cookie_name):
                csrf_header = request.headers.get("x-csrf-token")
                csrf_cookie = request.cookies.get("csrf_token")
                if not csrf_header or not csrf_cookie or csrf_header != csrf_cookie:
                    raise AppError(401, "unauthenticated", "CSRF token missing or invalid")
                origin = request.headers.get("origin")
                allowed = {item.strip() for item in settings.allowed_origins.split(",")}
                if origin is None or origin not in allowed:
                    raise AppError(401, "unauthenticated", "Origin is not allowed")
            return user_id, "cookie"
    raise AppError(401, "unauthenticated", "Authentication required")
