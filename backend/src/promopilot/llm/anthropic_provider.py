"""Anthropic, the secondary live provider (ADR 0001): `claude-sonnet-5` via ANTHROPIC_MODEL.

`claude-sonnet-5` rejects sampling parameters, so no temperature is sent; it runs with
adaptive thinking at effort "low" (ADR 0027). Thinking blocks come back in
`ToolTurn.provider_state` and are echoed unchanged in the next request of a tool round, as the
API requires. Failures surface as in `OpenAIProvider`: timeouts, dropped connections,
408/409/429 and 5xx (529 overloaded) as `TransientLLMError`, the rest as `LLMError`.
"""

from collections.abc import Sequence
from typing import Any

import anthropic
import pydantic
from anthropic.types import MessageParam, ToolParam
from anthropic.types import Usage as AnthropicUsage
from pydantic import BaseModel

from promopilot.llm.provider import (
    LLMError,
    Message,
    ToolCall,
    ToolSpec,
    ToolTurn,
    TransientLLMError,
    is_transient_status,
)
from promopilot.llm.usage import Usage, record_usage

MAX_TOKENS = 16_000
"""Room for the answer plus adaptive thinking, within non-streaming request limits."""

_THINKING_BLOCKS = frozenset({"thinking", "redacted_thinking"})


class AnthropicProvider:
    """Asks Claude for a schema-constrained answer or a tool-calling step."""

    def __init__(self, client: anthropic.AsyncAnthropic, *, model: str) -> None:
        self._client = client
        self._model = model

    async def complete_structured[T: BaseModel](
        self, schema: type[T], messages: Sequence[Message]
    ) -> T:
        what = schema.__name__
        system, wire = _wire(messages)
        try:
            response = await self._client.messages.parse(
                model=self._model,
                max_tokens=MAX_TOKENS,
                system=system,
                messages=wire,
                thinking={"type": "adaptive"},
                output_config={"effort": "low"},
                output_format=schema,
            )
        except (anthropic.AnthropicError, pydantic.ValidationError, ValueError) as error:
            raise self._error(what, error) from error
        self._bill(response.usage)
        if response.stop_reason == "refusal":
            raise LLMError(f"Anthropic {self._model} refused {what}")
        if response.parsed_output is None:
            raise LLMError(f"Anthropic {self._model} gave no {what} ({response.stop_reason})")
        return response.parsed_output

    async def complete_with_tools(
        self, tools: Sequence[ToolSpec], messages: Sequence[Message]
    ) -> ToolTurn:
        system, wire = _wire(messages)
        specs: list[ToolParam] = [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in tools
        ]
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=MAX_TOKENS,
                system=system,
                messages=wire,
                tools=specs,
                thinking={"type": "adaptive"},
                output_config={"effort": "low"},
            )
        except anthropic.AnthropicError as error:
            raise self._error("a tool turn", error) from error
        self._bill(response.usage)
        if response.stop_reason == "refusal":
            raise LLMError(f"Anthropic {self._model} refused a tool turn")
        texts: list[str] = []
        calls: list[ToolCall] = []
        state: list[dict[str, Any]] = []
        for block in response.content:
            if block.type == "text":
                texts.append(block.text)
            elif block.type == "tool_use":
                calls.append(ToolCall(id=block.id, name=block.name, arguments=dict(block.input)))
            elif block.type in _THINKING_BLOCKS:
                state.append(block.model_dump(mode="json", exclude_none=True))
        return ToolTurn(
            text="".join(texts) or None, tool_calls=tuple(calls), provider_state=tuple(state)
        )

    def _error(self, what: str, error: Exception) -> LLMError:
        text = f"Anthropic {self._model} failed on {what}: {error}"
        if isinstance(error, anthropic.APIConnectionError) or (
            isinstance(error, anthropic.APIStatusError) and is_transient_status(error.status_code)
        ):
            return TransientLLMError(text)
        return LLMError(text)

    def _bill(self, usage: AnthropicUsage) -> None:
        record_usage(
            Usage(
                model=self._model,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
            )
        )


def _wire(messages: Sequence[Message]) -> tuple[str | anthropic.Omit, list[MessageParam]]:
    """System turns become the top-level system prompt; each run of tool turns one user turn."""
    system = "\n\n".join(m.content for m in messages if m.role == "system")
    wire: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "system":
            continue
        if m.role == "tool":
            result = {"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content}
            last = wire[-1] if wire else None
            if last is not None and last["role"] == "user" and isinstance(last["content"], list):
                last["content"].append(result)
            else:
                wire.append({"role": "user", "content": [result]})
        elif m.role == "assistant" and (m.tool_calls or m.provider_state):
            blocks: list[dict[str, Any]] = list(m.provider_state)
            if m.content:
                blocks.append({"type": "text", "text": m.content})
            blocks += [
                {"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments}
                for c in m.tool_calls
            ]
            wire.append({"role": "assistant", "content": blocks})
        else:
            wire.append({"role": m.role, "content": m.content})
    return (system or anthropic.omit), wire  # type: ignore[return-value]
