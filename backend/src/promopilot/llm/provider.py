"""The vendor-neutral interface every agent talks to (SPEC §9.6, ADR 0001, ADR 0027)."""

from collections.abc import Sequence
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

STRUCTURED_TEMPERATURE = 0.0
"""Structured and tool-calling steps are deterministic (SPEC §6, §9.6)."""


class ToolCall(BaseModel):
    """One tool the model asked to run, with its JSON arguments."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    arguments: dict[str, Any]


class Message(BaseModel):
    """One chat turn sent to a provider.

    An assistant turn may carry the `tool_calls` it made, and a `tool` turn answers one of them
    by `tool_call_id`. `provider_state` holds opaque blocks a provider needs echoed back
    unchanged (Anthropic's thinking blocks within a tool round); it is never part of a request
    hash.
    """

    model_config = ConfigDict(frozen=True)

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    provider_state: tuple[dict[str, Any], ...] = ()


class ToolSpec(BaseModel):
    """A tool offered to the model: its name, what it does and its JSON-Schema input."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    input_schema: dict[str, Any]


class ToolTurn(BaseModel):
    """One model step over tools: some text, the tools it wants run, or both."""

    model_config = ConfigDict(frozen=True)

    text: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    provider_state: tuple[dict[str, Any], ...] = Field(default=(), repr=False)

    def as_message(self) -> Message:
        """The assistant turn to append to the conversation before sending the tool results."""
        return Message(
            role="assistant",
            content=self.text or "",
            tool_calls=self.tool_calls,
            provider_state=self.provider_state,
        )


class LLMError(Exception):
    """A provider could not produce a valid response."""


class TransientLLMError(LLMError):
    """A failure worth retrying: a timeout, a dropped connection, rate limiting or a 5xx."""


TRANSIENT_STATUSES = frozenset({408, 409, 429})


def is_transient_status(status: int) -> bool:
    """HTTP statuses a retry can fix: timeouts, conflicts, rate limits and any 5xx (529 too)."""
    return status in TRANSIENT_STATUSES or status >= 500


class LLMProvider(Protocol):
    async def complete_structured[T: BaseModel](
        self, schema: type[T], messages: Sequence[Message]
    ) -> T:
        """Return the model's answer to `messages`, parsed as `schema`."""
        ...

    async def complete_with_tools(
        self, tools: Sequence[ToolSpec], messages: Sequence[Message]
    ) -> ToolTurn:
        """Return the model's next step: text and/or the tool calls it wants run."""
        ...
