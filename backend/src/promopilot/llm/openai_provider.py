"""OpenAI, the primary live provider (ADR 0001): structured outputs and function calling.

Every failure surfaces as an `LLMError`; timeouts, dropped connections, 408/409/429 and 5xx
as a `TransientLLMError` for `RetryingProvider` (ADR 0027). Build the client with
`max_retries=0` so retries happen only there. Each answer reports its usage under the
configured model id, which is what prices are keyed by.
"""

import json
from collections.abc import Sequence
from typing import Any

import openai
import pydantic
from openai.types.chat import ChatCompletionMessageParam, ChatCompletionToolParam
from openai.types.completion_usage import CompletionUsage
from pydantic import BaseModel

from promopilot.llm.provider import (
    STRUCTURED_TEMPERATURE,
    LLMError,
    Message,
    ToolCall,
    ToolSpec,
    ToolTurn,
    TransientLLMError,
    is_transient_status,
)
from promopilot.llm.usage import Usage, record_usage


class OpenAIProvider:
    """Asks OpenAI for a schema-constrained answer or a tool-calling step."""

    def __init__(self, client: openai.AsyncOpenAI, *, model: str) -> None:
        self._client = client
        self._model = model

    async def complete_structured[T: BaseModel](
        self, schema: type[T], messages: Sequence[Message]
    ) -> T:
        what = schema.__name__
        try:
            completion = await self._client.chat.completions.parse(
                model=self._model,
                messages=_wire(messages),
                response_format=schema,
                temperature=STRUCTURED_TEMPERATURE,
            )
        except (openai.OpenAIError, pydantic.ValidationError) as error:
            raise self._error(what, error) from error
        self._bill(completion.usage)
        message = completion.choices[0].message
        if message.parsed is None:
            raise LLMError(f"OpenAI {self._model} gave no {what}: {message.refusal}")
        return message.parsed

    async def complete_with_tools(
        self, tools: Sequence[ToolSpec], messages: Sequence[Message]
    ) -> ToolTurn:
        functions: list[ChatCompletionToolParam] = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                },
            }
            for tool in tools
        ]
        try:
            completion = await self._client.chat.completions.create(
                model=self._model,
                messages=_wire(messages),
                tools=functions,
                temperature=STRUCTURED_TEMPERATURE,
            )
        except openai.OpenAIError as error:
            raise self._error("a tool turn", error) from error
        self._bill(completion.usage)
        message = completion.choices[0].message
        calls = []
        for call in message.tool_calls or []:
            if call.type != "function":
                raise LLMError(f"OpenAI {self._model} made an unsupported {call.type} tool call")
            try:
                arguments = json.loads(call.function.arguments)
            except json.JSONDecodeError as error:
                raise LLMError(
                    f"OpenAI {self._model} sent unparseable arguments for "
                    f"{call.function.name}: {error}"
                ) from error
            calls.append(ToolCall(id=call.id, name=call.function.name, arguments=arguments))
        return ToolTurn(text=message.content or None, tool_calls=tuple(calls))

    def _error(self, what: str, error: Exception) -> LLMError:
        text = f"OpenAI {self._model} failed on {what}: {error}"
        if isinstance(error, openai.APIConnectionError) or (
            isinstance(error, openai.APIStatusError) and is_transient_status(error.status_code)
        ):
            return TransientLLMError(text)
        return LLMError(text)

    def _bill(self, usage: CompletionUsage | None) -> None:
        if usage is not None:
            record_usage(
                Usage(
                    model=self._model,
                    input_tokens=usage.prompt_tokens,
                    output_tokens=usage.completion_tokens,
                )
            )


def _wire(messages: Sequence[Message]) -> list[ChatCompletionMessageParam]:
    wire: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "tool":
            wire.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content})
        elif m.tool_calls:
            wire.append(
                {
                    "role": "assistant",
                    "content": m.content or None,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(call.arguments),
                            },
                        }
                        for call in m.tool_calls
                    ],
                }
            )
        else:
            wire.append({"role": m.role, "content": m.content})
    return wire  # type: ignore[return-value]
