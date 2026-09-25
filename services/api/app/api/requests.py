"""Shared request parsing for JSON endpoints."""

import hashlib
import json
from uuid import UUID

from fastapi import Request

from app.api.errors import AppError


def require_idempotency_key(request: Request) -> UUID:
    raw = request.headers.get("idempotency-key")
    if raw is None:
        raise AppError(400, "validation_failed", "Idempotency-Key header is required")
    try:
        return UUID(raw)
    except ValueError:
        raise AppError(400, "validation_failed", "Idempotency-Key must be a UUID") from None


def fingerprint(raw_body: bytes, method: str, path: str) -> str:
    return hashlib.sha256(raw_body + b"\n" + method.encode() + b"\n" + path.encode()).hexdigest()


def parse_json_object(raw_body: bytes) -> dict[str, object]:
    if not raw_body.strip():
        return {}
    try:
        parsed = json.loads(raw_body)
    except (ValueError, UnicodeDecodeError):
        raise AppError(400, "validation_failed", "Request body must be valid JSON") from None
    if not isinstance(parsed, dict):
        raise AppError(400, "validation_failed", "Request body must be a JSON object")
    return parsed


def reject_unknown(body: dict[str, object], allowed: set[str]) -> None:
    if set(body) - allowed:
        raise AppError(400, "validation_failed", "Request body contains unknown fields")


async def read_json_body(request: Request, allowed: set[str]) -> tuple[bytes, dict[str, object]]:
    raw_body = await request.body()
    body = parse_json_object(raw_body)
    reject_unknown(body, allowed)
    return raw_body, body
