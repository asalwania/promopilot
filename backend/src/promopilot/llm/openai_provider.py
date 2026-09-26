"""OpenAI, the primary live provider (ADR 0001), via structured outputs."""

from collections.abc import Sequence

import openai
import pydantic
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

from promopilot.llm.provider import STRUCTURED_TEMPERATURE, LLMError, Message


class OpenAIProvider:
    """Asks OpenAI for a JSON-Schema-constrained answer; every failure surfaces as `LLMError`."""

    def __init__(self, client: openai.AsyncOpenAI, *, model: str) -> None:
        self._client = client
        self._model = model

    async def complete_structured[T: BaseModel](
        self, schema: type[T], messages: Sequence[Message]
    ) -> T:
        wire: list[ChatCompletionMessageParam] = [
            {"role": m.role, "content": m.content}  # type: ignore[misc]
            for m in messages
        ]
        try:
            completion = await self._client.chat.completions.parse(
                model=self._model,
                messages=wire,
                response_format=schema,
                temperature=STRUCTURED_TEMPERATURE,
            )
        except (openai.OpenAIError, pydantic.ValidationError) as error:
            raise LLMError(f"OpenAI {self._model} failed on {schema.__name__}: {error}") from error
        message = completion.choices[0].message
        if message.parsed is None:
            raise LLMError(f"OpenAI {self._model} gave no {schema.__name__}: {message.refusal}")
        return message.parsed
