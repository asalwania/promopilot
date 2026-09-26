"""A scripted provider for tests: no network, no key."""

from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import BaseModel

from promopilot.llm.provider import Message


@dataclass(frozen=True)
class FakeCall:
    schema: type[BaseModel]
    messages: list[Message]


class FakeProvider:
    """Answers each call with the next scripted response, or raises it if it is an exception."""

    def __init__(self, script: Sequence[BaseModel | Exception]) -> None:
        self._script = list(script)
        self.calls: list[FakeCall] = []

    async def complete_structured[T: BaseModel](
        self, schema: type[T], messages: Sequence[Message]
    ) -> T:
        self.calls.append(FakeCall(schema, list(messages)))
        if not self._script:
            raise AssertionError(f"FakeProvider script exhausted at call {len(self.calls)}")
        step = self._script.pop(0)
        if isinstance(step, Exception):
            raise step
        if not isinstance(step, schema):
            raise AssertionError(f"scripted {type(step).__name__}, but {schema.__name__} asked")
        return step
