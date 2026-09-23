import asyncio
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Protocol

from app.chat.event_writer import Usage


@dataclass(frozen=True)
class ProviderMessage:
    role: str
    content: str


@dataclass(frozen=True)
class ProviderError:
    code: str
    message: str


@dataclass(frozen=True)
class ProviderDelta:
    text: str = ""
    finish_reason: str | None = None
    usage: Usage | None = None
    error: ProviderError | None = None


class ProviderStreamError(Exception):
    def __init__(self, error: ProviderError) -> None:
        super().__init__(error.code)
        self.error = error


class CancelSignal:
    def __init__(self) -> None:
        self._event = asyncio.Event()

    def set(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    async def wait(self) -> None:
        await self._event.wait()


class LlmProvider(Protocol):
    def stream(
        self,
        messages: Sequence[ProviderMessage],
        *,
        signal: CancelSignal,
    ) -> AsyncIterator[ProviderDelta]: ...
