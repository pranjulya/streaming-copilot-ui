import json
from collections.abc import AsyncIterator, Sequence

import httpx

from app.chat.event_writer import Usage
from app.providers.protocol import (
    CancelSignal,
    ProviderDelta,
    ProviderError,
    ProviderMessage,
    ProviderStreamError,
)
from app.settings import Settings


def _protocol_error(message: str) -> ProviderStreamError:
    return ProviderStreamError(ProviderError(code="provider_protocol_error", message=message))


class XaiProvider:
    """Streams the xAI Responses API, mapping output text to ProviderDelta."""

    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._settings = settings
        self._transport = transport

    async def stream(
        self,
        messages: Sequence[ProviderMessage],
        *,
        signal: CancelSignal,
    ) -> AsyncIterator[ProviderDelta]:
        settings = self._settings
        api_key = settings.xai_api_key.get_secret_value().strip() if settings.xai_api_key else ""
        if not api_key:
            raise ProviderStreamError(
                ProviderError(code="provider_unavailable", message="xAI key is not configured.")
            )
        payload = {
            "model": settings.xai_model,
            "stream": True,
            "store": False,
            "input": [{"role": message.role, "content": message.content} for message in messages],
        }
        timeout = httpx.Timeout(
            settings.provider_idle_timeout_seconds,
            connect=settings.provider_connect_timeout_seconds,
        )
        finished = False
        async with httpx.AsyncClient(
            base_url=settings.xai_base_url, timeout=timeout, transport=self._transport
        ) as client:
            async with client.stream(
                "POST",
                "/responses",
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
            ) as response:
                if response.status_code == 429:
                    raise ProviderStreamError(
                        ProviderError(
                            code="provider_rate_limited",
                            message="The assistant is temporarily rate limited.",
                        )
                    )
                if response.status_code >= 500:
                    raise ProviderStreamError(
                        ProviderError(
                            code="provider_unavailable",
                            message="The assistant is temporarily unavailable.",
                        )
                    )
                if response.status_code >= 400:
                    raise _protocol_error("The provider rejected the request.")
                async for line in response.aiter_lines():
                    if signal.cancelled:
                        return
                    if not line.startswith("data:"):
                        continue
                    raw = line[len("data:") :].strip()
                    if not raw or raw == "[DONE]":
                        continue
                    try:
                        event = json.loads(raw)
                    except ValueError:
                        raise _protocol_error("The provider sent malformed data.") from None
                    if not isinstance(event, dict):
                        raise _protocol_error("The provider sent malformed data.")
                    event_type = event.get("type", "")
                    if event_type == "response.output_text.delta":
                        text = event.get("delta")
                        if isinstance(text, str) and text:
                            yield ProviderDelta(text=text)
                    elif event_type == "response.completed":
                        finished = True
                        yield ProviderDelta(
                            finish_reason=_finish_reason(event),
                            usage=_usage(event),
                        )
                        return
                    elif event_type == "error":
                        raise ProviderStreamError(
                            ProviderError(
                                code="provider_unavailable",
                                message="The assistant is temporarily unavailable.",
                            )
                        )
        if not finished and not signal.cancelled:
            raise _protocol_error("The provider stream ended unexpectedly.")


def _finish_reason(event: dict[str, object]) -> str:
    response = event.get("response")
    if isinstance(response, dict):
        status = response.get("status")
        if status == "incomplete":
            return "length"
    return "stop"


def _usage(event: dict[str, object]) -> Usage | None:
    response = event.get("response")
    if not isinstance(response, dict):
        return None
    usage = response.get("usage")
    if not isinstance(usage, dict):
        return None
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    if isinstance(input_tokens, int) and isinstance(output_tokens, int):
        return Usage(input_tokens=input_tokens, output_tokens=output_tokens)
    return None
