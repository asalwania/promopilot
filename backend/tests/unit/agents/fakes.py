"""An in-memory stand-in for `promopilot.data.RetailData`, backed by a generated dataset, and
scripted LLM steps shared by agent tests."""

from collections.abc import Sequence

import pandas as pd
from pydantic import BaseModel

from promopilot import data
from promopilot.datagen import GeneratedDataset
from promopilot.llm import LLMError, Message, ToolSpec, ToolTurn


def explainer_down() -> LLMError:
    """A scripted FakeProvider step for the Explainer: its LLM fails, so the template explains
    the plan revision (ADR 0050)."""
    return LLMError("the Explainer's LLM is down in this test")


class DownProvider:
    """An LLM that is down for good: every call raises `LLMError`, and is counted."""

    def __init__(self) -> None:
        self.calls = 0

    async def complete_structured[T: BaseModel](
        self, schema: type[T], messages: Sequence[Message]
    ) -> T:
        self.calls += 1
        raise LLMError("the LLM is down in this test")

    async def complete_with_tools(
        self, tools: Sequence[ToolSpec], messages: Sequence[Message]
    ) -> ToolTurn:
        self.calls += 1
        raise LLMError("the LLM is down in this test")


class InMemoryRetailData(data.InMemoryRetailData):
    """`promopilot.data.InMemoryRetailData` that notes every as-of week the inventory was read
    at, so tests can check the clock."""

    def __init__(self, dataset: GeneratedDataset) -> None:
        super().__init__(dataset)
        self.inventory_as_of_weeks: list[int] = []

    async def inventory(self, as_of_week: int) -> pd.DataFrame:
        self.inventory_as_of_weeks.append(as_of_week)
        return await super().inventory(as_of_week)
