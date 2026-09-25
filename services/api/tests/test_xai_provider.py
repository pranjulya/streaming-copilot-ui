import asyncio
import json

import httpx
import pytest

from tests.support import build_settings


def xai_settings(**overrides: object):
    values: dict[str, object] = {
        "app_env": "production",
        "xai_api_key": "test-key",
        "xai_base_url": "https://api.x.ai/v1",
        "auth_jwt_issuer": "https://auth.example.test",
        "auth_jwt_audience": "copilot",
        "auth_jwt_jwks_url": "https://auth.example.test/jwks.json",
    }
    values.update(overrides)
    return build_settings(**values)


def sse(*events: dict) -> bytes:
    return b"".join(f"data: {json.dumps(event)}\n\n".encode() for event in events)


def test_xai_adapter_maps_text_deltas_and_drops_reasoning() -> None:
    from app.providers.xai import XaiProvider

    seen_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse(
                {"type": "response.created"},
                {"type": "response.reasoning_summary_text.delta", "delta": "hidden chain"},
                {"type": "response.output_text.delta", "delta": "Back"},
                {"type": "response.output_text.delta", "delta": "pressure"},
                {"type": "response.output_text.done", "text": "Backpressure"},
                {
                    "type": "response.completed",
                    "response": {"usage": {"input_tokens": 7, "output_tokens": 4}},
                },
            ),
        )

    async def scenario() -> None:
        from app.providers.protocol import CancelSignal, ProviderMessage

        provider = XaiProvider(xai_settings(), transport=httpx.MockTransport(handler))
        deltas = [
            delta
            async for delta in provider.stream(
                [ProviderMessage(role="user", content="hi")], signal=CancelSignal()
            )
        ]
        texts = "".join(delta.text for delta in deltas)
        assert texts == "Backpressure"
        assert all("hidden chain" not in delta.text for delta in deltas)
        assert deltas[-1].finish_reason == "stop"
        assert deltas[-1].usage is not None
        assert deltas[-1].usage.input_tokens == 7
        assert seen_requests[0].url.path == "/v1/responses"
        assert seen_requests[0].headers["authorization"] == "Bearer test-key"
        payload = json.loads(seen_requests[0].content)
        assert payload["model"] == "grok-4.6"
        assert payload["stream"] is True
        assert payload["store"] is False
        assert payload["input"][0]["role"] == "user"

    asyncio.run(scenario())


def test_xai_adapter_maps_http_failures_to_provider_codes() -> None:
    from app.providers.protocol import CancelSignal, ProviderStreamError
    from app.providers.xai import XaiProvider

    async def scenario() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"error": "rate limited"})

        provider = XaiProvider(xai_settings(), transport=httpx.MockTransport(handler))
        with pytest.raises(ProviderStreamError) as caught:
            async for _ in provider.stream([], signal=CancelSignal()):
                pass
        assert caught.value.error.code == "provider_rate_limited"

    asyncio.run(scenario())


def test_xai_adapter_stops_after_response_completed() -> None:
    from app.providers.protocol import CancelSignal, ProviderMessage
    from app.providers.xai import XaiProvider

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse(
                {
                    "type": "response.completed",
                    "response": {"usage": {"input_tokens": 1, "output_tokens": 1}},
                },
                {"type": "error"},
            ),
        )

    async def scenario() -> None:
        provider = XaiProvider(xai_settings(), transport=httpx.MockTransport(handler))
        deltas = [
            delta
            async for delta in provider.stream(
                [ProviderMessage(role="user", content="hi")], signal=CancelSignal()
            )
        ]
        assert len(deltas) == 1
        assert deltas[-1].finish_reason == "stop"

    asyncio.run(scenario())


@pytest.mark.live
def test_xai_live_smoke_is_opt_in() -> None:
    import os

    api_key = os.getenv("XAI_API_KEY")
    if not api_key:
        pytest.skip("XAI_API_KEY is not set; live provider tests are opt-in")

    from app.providers.protocol import CancelSignal, ProviderMessage
    from app.providers.xai import XaiProvider

    async def scenario() -> None:
        provider = XaiProvider(xai_settings(xai_api_key=api_key))
        deltas = [
            delta
            async for delta in provider.stream(
                [ProviderMessage(role="user", content="Reply with exactly: ok")],
                signal=CancelSignal(),
            )
        ]
        assert deltas[-1].finish_reason is not None, "live stream must finish"
        assert "".join(delta.text for delta in deltas).strip(), "live stream must return text"

    asyncio.run(scenario())
