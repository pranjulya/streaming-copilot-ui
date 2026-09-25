import asyncio

import pytest


def test_fake_provider_default_finish_includes_zero_usage() -> None:
    from app.providers.fake import FakeProvider
    from app.providers.protocol import CancelSignal

    async def scenario() -> None:
        provider = FakeProvider()
        deltas = [delta async for delta in provider.stream([], signal=CancelSignal())]
        assert deltas[-1].finish_reason == "stop"
        assert deltas[-1].usage is not None
        assert deltas[-1].usage.input_tokens == 0
        assert deltas[-1].usage.output_tokens == 0

    asyncio.run(scenario())


def test_fake_provider_uses_long_delay_when_user_marks_the_prompt() -> None:
    import time

    from app.providers.fake import FakeProvider
    from app.providers.protocol import CancelSignal, ProviderMessage

    provider = FakeProvider(deltas=["x"], delay_seconds=0.0, long_delay_seconds=0.05)

    async def timed(content: str) -> float:
        started = time.perf_counter()
        async for _ in provider.stream(
            [ProviderMessage(role="user", content=content)], signal=CancelSignal()
        ):
            pass
        return time.perf_counter() - started

    assert asyncio.run(timed("load rehearsal")) < 0.04
    assert asyncio.run(timed("load rehearsal [long]")) >= 0.04


def test_fake_provider_streams_scripted_text_and_finish() -> None:
    from app.providers.fake import FakeProvider
    from app.providers.protocol import CancelSignal, ProviderMessage, Usage

    async def scenario() -> None:
        provider = FakeProvider(
            deltas=["Back", "pressure"], finish_reason="stop", usage=Usage(1, 2)
        )
        deltas = [
            delta
            async for delta in provider.stream(
                [ProviderMessage(role="user", content="hi")], signal=CancelSignal()
            )
        ]
        assert "".join(delta.text for delta in deltas) == "Backpressure"
        assert deltas[-1].finish_reason == "stop"
        assert deltas[-1].usage == Usage(1, 2)

    asyncio.run(scenario())


def test_fake_provider_fails_after_n_deltas_with_error_code() -> None:
    from app.providers.fake import FakeProvider
    from app.providers.protocol import (
        CancelSignal,
        ProviderError,
        ProviderStreamError,
    )

    async def scenario() -> None:
        provider = FakeProvider(
            deltas=["a", "b", "c"],
            fail_after=2,
            failure=ProviderError(code="provider_unavailable", message="down"),
        )
        collected: list[str] = []
        with pytest.raises(ProviderStreamError) as caught:
            async for delta in provider.stream([], signal=CancelSignal()):
                collected.append(delta.text)
        assert collected == ["a", "b"]
        assert caught.value.error.code == "provider_unavailable"

    asyncio.run(scenario())


def test_fake_provider_stops_when_cancel_signal_is_set() -> None:
    from app.providers.fake import FakeProvider
    from app.providers.protocol import CancelSignal

    async def scenario() -> None:
        provider = FakeProvider(deltas=["x"] * 500, delay_seconds=0.001)
        signal = CancelSignal()
        collected: list[str] = []

        async def consume() -> None:
            async for delta in provider.stream([], signal=signal):
                collected.append(delta.text)
                if len(collected) == 3:
                    signal.set()

        await asyncio.wait_for(consume(), 5)
        assert 3 <= len(collected) < 500

    asyncio.run(scenario())


def test_fake_provider_can_ignore_cancel_until_killed() -> None:
    from app.providers.fake import FakeProvider
    from app.providers.protocol import CancelSignal

    async def scenario() -> None:
        provider = FakeProvider(deltas=["x"] * 500, delay_seconds=0.005, ignores_cancel=True)
        signal = CancelSignal()
        signal.set()
        collected: list[str] = []
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(_consume_into(provider, signal, collected), 0.2)
        assert collected

    asyncio.run(scenario())


async def _consume_into(provider, signal, collected: list[str]) -> None:
    async for delta in provider.stream([], signal=signal):
        collected.append(delta.text)
