import json
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any
from uuid import uuid4

from app.api.errors import PROBLEM_TYPE_BASE

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]


class RequestBodyLimitMiddleware:
    """Reject oversized bodies from Content-Length or accumulated chunks."""

    def __init__(
        self, app: Callable[[Scope, Receive, Send], Awaitable[None]], max_bytes: int
    ) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        length = headers.get("content-length")
        if length is not None:
            try:
                if int(length) > self.max_bytes:
                    await _send_413(send)
                    return
            except ValueError:
                pass
        received = 0
        rejected = False

        async def limited_receive() -> Message:
            nonlocal received, rejected
            if rejected:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body") or b"")
                if received > self.max_bytes:
                    rejected = True
                    await _send_413(send)
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            if rejected:
                return
            await send(message)

        await self.app(scope, limited_receive, guarded_send)


async def _send_413(send: Send) -> None:
    payload = json.dumps(
        {
            "type": f"{PROBLEM_TYPE_BASE}payload_too_large",
            "title": "Request body is too large",
            "status": 413,
            "code": "payload_too_large",
            "diagnostic_id": str(uuid4()),
        }
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/problem+json"),
                (b"content-length", str(len(payload)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": payload})
