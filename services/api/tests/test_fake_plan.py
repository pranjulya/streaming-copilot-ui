import asyncio

import pytest

from tests.support import database_url


def test_planned_fake_provider_cycles_steps_and_repeats_the_last() -> None:
    from app.providers.fake import FakeProvider, PlannedFakeProvider
    from app.providers.protocol import CancelSignal, ProviderStreamError

    async def scenario() -> None:
        first = FakeProvider(deltas=["a"], fail_after=1)
        second = FakeProvider(deltas=["o", "k"], finish_reason="stop")
        provider = PlannedFakeProvider([first, second])

        with pytest.raises(ProviderStreamError):
            async for _ in provider.stream([], signal=CancelSignal()):
                pass

        for _ in range(2):
            texts = [delta.text async for delta in provider.stream([], signal=CancelSignal())]
            assert "".join(texts) == "ok"

    asyncio.run(scenario())


def test_build_provider_honours_the_fake_plan_environment(monkeypatch) -> None:
    import json

    from app.main import _build_provider
    from app.providers.fake import PlannedFakeProvider
    from app.providers.protocol import CancelSignal
    from app.settings import Settings

    monkeypatch.setenv(
        "FAKE_PROVIDER_PLAN",
        json.dumps([{"deltas": ["plan"], "delay_seconds": 0.0}]),
    )
    settings = Settings(_env_file=None, database_url=database_url(), app_env="development")
    provider = _build_provider(settings)
    assert isinstance(provider, PlannedFakeProvider)

    async def collect() -> str:
        texts = [delta.text async for delta in provider.stream([], signal=CancelSignal())]
        return "".join(texts)

    assert asyncio.run(collect()) == "plan"
