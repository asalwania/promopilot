"""Retry with exponential backoff, then fall back to the secondary provider (SF-03, ADR 0027).

`build_provider` composes them as `FallbackProvider(Retrying(primary), Retrying(secondary))`.
Only a `TransientLLMError` is retried; once the primary gives up, for any `LLMError`, the
secondary gets the same request.
"""

import asyncio
from collections.abc import Awaitable, Callable, Sequence

import structlog
from pydantic import BaseModel

from promopilot.llm.provider import (
    LLMError,
    LLMProvider,
    Message,
    ToolSpec,
    ToolTurn,
    TransientLLMError,
)

log = structlog.get_logger(__name__)

Sleep = Callable[[float], Awaitable[None]]


class RetryingProvider:
    """Retries transient failures: `max_attempts` calls in all, waiting base, 2x base, ... cap."""

    def __init__(
        self,
        inner: LLMProvider,
        *,
        max_attempts: int = 3,
        base_delay_s: float = 1.0,
        max_delay_s: float = 8.0,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self._inner = inner
        self._max_attempts = max_attempts
        self._base_delay_s = base_delay_s
        self._max_delay_s = max_delay_s
        self._sleep = sleep

    async def complete_structured[T: BaseModel](
        self, schema: type[T], messages: Sequence[Message]
    ) -> T:
        return await self._retry(lambda: self._inner.complete_structured(schema, messages))

    async def complete_with_tools(
        self, tools: Sequence[ToolSpec], messages: Sequence[Message]
    ) -> ToolTurn:
        return await self._retry(lambda: self._inner.complete_with_tools(tools, messages))

    async def _retry[R](self, call: Callable[[], Awaitable[R]]) -> R:
        attempt = 1
        while True:
            try:
                return await call()
            except TransientLLMError as error:
                if attempt >= self._max_attempts:
                    raise
                delay = min(self._base_delay_s * 2 ** (attempt - 1), self._max_delay_s)
                log.warning("llm_retry", attempt=attempt, delay_s=delay, error=str(error))
                await self._sleep(delay)
                attempt += 1


class FallbackProvider:
    """Sends a request to `secondary` when `primary` fails with any `LLMError`."""

    def __init__(self, primary: LLMProvider, secondary: LLMProvider) -> None:
        self._primary = primary
        self._secondary = secondary

    async def complete_structured[T: BaseModel](
        self, schema: type[T], messages: Sequence[Message]
    ) -> T:
        return await self._fall_back(
            lambda: self._primary.complete_structured(schema, messages),
            lambda: self._secondary.complete_structured(schema, messages),
        )

    async def complete_with_tools(
        self, tools: Sequence[ToolSpec], messages: Sequence[Message]
    ) -> ToolTurn:
        return await self._fall_back(
            lambda: self._primary.complete_with_tools(tools, messages),
            lambda: self._secondary.complete_with_tools(tools, messages),
        )

    async def _fall_back[R](
        self, primary: Callable[[], Awaitable[R]], secondary: Callable[[], Awaitable[R]]
    ) -> R:
        try:
            return await primary()
        except LLMError as first:
            log.warning("llm_fallback", error=str(first))
            try:
                return await secondary()
            except LLMError as second:
                raise LLMError(f"primary failed: {first}; secondary failed: {second}") from second
