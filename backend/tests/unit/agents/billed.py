"""A provider double that bills each call like a live provider does (ADR 0027), so token-usage
trace events can be tested with no network and no key."""

from collections.abc import Sequence

from pydantic import BaseModel

from promopilot.llm import LLMProvider, Message, ToolSpec, ToolTurn, Usage, record_usage


class BilledProvider:
    """Answers through `inner`, reporting the next of `usages` for every call it makes, even a
    call that fails, as a live provider reports a billed refusal."""

    def __init__(self, inner: LLMProvider, usages: Sequence[Usage]) -> None:
        self._inner = inner
        self._usages = list(usages)

    async def complete_structured[T: BaseModel](
        self, schema: type[T], messages: Sequence[Message]
    ) -> T:
        self._bill()
        return await self._inner.complete_structured(schema, messages)

    async def complete_with_tools(
        self, tools: Sequence[ToolSpec], messages: Sequence[Message]
    ) -> ToolTurn:
        self._bill()
        return await self._inner.complete_with_tools(tools, messages)

    def _bill(self) -> None:
        if not self._usages:
            raise AssertionError("BilledProvider has no usage left to bill")
        record_usage(self._usages.pop(0))
