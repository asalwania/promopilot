"""A scripted provider for tests: no network, no key."""

from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import BaseModel

from promopilot.llm.provider import Message, ToolSpec, ToolTurn


@dataclass(frozen=True)
class FakeCall:
    """One call made: `schema` for a structured call, `tools` for a tool call."""

    schema: type[BaseModel] | None
    messages: list[Message]
    tools: tuple[ToolSpec, ...] = ()


class FakeProvider:
    """Answers each call with the next scripted response, or raises it if it is an exception."""

    def __init__(self, script: Sequence[BaseModel | Exception]) -> None:
        self._script = list(script)
        self.calls: list[FakeCall] = []

    async def complete_structured[T: BaseModel](
        self, schema: type[T], messages: Sequence[Message]
    ) -> T:
        self.calls.append(FakeCall(schema, list(messages)))
        step = self._next()
        if not isinstance(step, schema):
            raise AssertionError(f"scripted {type(step).__name__}, but {schema.__name__} asked")
        return step

    async def complete_with_tools(
        self, tools: Sequence[ToolSpec], messages: Sequence[Message]
    ) -> ToolTurn:
        self.calls.append(FakeCall(None, list(messages), tuple(tools)))
        step = self._next()
        if not isinstance(step, ToolTurn):
            raise AssertionError(f"scripted {type(step).__name__}, but a tool turn asked")
        return step

    def _next(self) -> BaseModel:
        if not self._script:
            raise AssertionError(f"FakeProvider script exhausted at call {len(self.calls)}")
        step = self._script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step
