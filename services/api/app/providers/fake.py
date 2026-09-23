import asyncio
from collections.abc import AsyncIterator, Sequence

from app.chat.event_writer import Usage
from app.providers.protocol import (
    CancelSignal,
    ProviderDelta,
    ProviderError,
    ProviderMessage,
    ProviderStreamError,
)


class FakeProvider:
    """Deterministic scripted provider for tests and keyless local development."""

    def __init__(
        self,
        *,
        deltas: Sequence[str] = (),
        finish_reason: str = "stop",
        usage: Usage | None = None,
        fail_after: int | None = None,
        failure: ProviderError | None = None,
        ignores_cancel: bool = False,
        delay_seconds: float = 0.0,
        hang_after: int | None = None,
    ) -> None:
        self.deltas = list(deltas)
        self.finish_reason = finish_reason
        self.usage = usage
        self.fail_after = fail_after
        self.failure = failure or ProviderError(
            code="provider_unavailable", message="The assistant is temporarily unavailable."
        )
        self.ignores_cancel = ignores_cancel
        self.delay_seconds = delay_seconds
        self.hang_after = hang_after

    async def stream(
        self,
        messages: Sequence[ProviderMessage],
        *,
        signal: CancelSignal,
    ) -> AsyncIterator[ProviderDelta]:
        del messages
        for index, text in enumerate(self.deltas):
            if self.hang_after is not None and index == self.hang_after:
                await asyncio.Event().wait()
            if signal.cancelled and not self.ignores_cancel:
                return
            if self.delay_seconds:
                await asyncio.sleep(self.delay_seconds)
            if self.fail_after is not None and index == self.fail_after:
                raise ProviderStreamError(self.failure)
            yield ProviderDelta(text=text)
        if self.fail_after is not None and self.fail_after >= len(self.deltas):
            raise ProviderStreamError(self.failure)
        yield ProviderDelta(finish_reason=self.finish_reason, usage=self.usage)
