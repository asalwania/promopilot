"""The vendor-neutral interface every agent talks to (SPEC §9.6, ADR 0001)."""

from collections.abc import Sequence
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

STRUCTURED_TEMPERATURE = 0.0
"""Structured steps are deterministic (SPEC §6, §9.6)."""


class Message(BaseModel):
    """One chat turn sent to a provider."""

    model_config = ConfigDict(frozen=True)

    role: Literal["system", "user", "assistant"]
    content: str


class LLMError(Exception):
    """A provider could not produce a valid structured response."""


class LLMProvider(Protocol):
    async def complete_structured[T: BaseModel](
        self, schema: type[T], messages: Sequence[Message]
    ) -> T:
        """Return the model's answer to `messages`, parsed as `schema`."""
        ...
