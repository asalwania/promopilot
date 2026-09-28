"""An in-memory stand-in for `promopilot.data.RetailData`, backed by a generated dataset, and
scripted LLM steps shared by agent tests."""

import json
from collections.abc import Sequence

import pandas as pd
from pydantic import BaseModel

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


class InMemoryRetailData:
    """Answers the as-of-week queries the planning session makes, like Postgres would."""

    def __init__(self, dataset: GeneratedDataset) -> None:
        self._dataset = dataset
        self.inventory_as_of_weeks: list[int] = []
        """Every as-of week the inventory was read at, so tests can check the clock."""

    async def inventory(self, as_of_week: int) -> pd.DataFrame:
        self.inventory_as_of_weeks.append(as_of_week)
        stock = self._dataset.inventory
        snapshot = stock[stock["snapshot_week"] == as_of_week - 1]
        if snapshot.empty:
            raise LookupError(f"no inventory snapshot for the end of week {as_of_week - 1}")
        return snapshot.sort_values(["store_id", "sku_id"]).reset_index(drop=True)

    async def products(self) -> pd.DataFrame:
        return self._dataset.products.sort_values("sku_id").reset_index(drop=True)

    async def stores(self) -> pd.DataFrame:
        return self._dataset.stores.sort_values("store_id").reset_index(drop=True)

    async def calendar(self) -> pd.DataFrame:
        frame = self._dataset.calendar.sort_values(["region", "week_id"])
        return frame.reset_index(drop=True)

    async def sales_history(
        self, as_of_week: int, *, since_week: int | None = None
    ) -> pd.DataFrame:
        sales = self._dataset.sales_weekly
        visible = sales[
            (sales["week_id"] < as_of_week) & (sales["week_id"] >= (since_week or 0))
        ].copy()
        # Postgres returns the JSONB column already decoded.
        visible["segment_units"] = visible["segment_units"].map(json.loads)
        return visible.reset_index(drop=True)

    async def latest_competitor_prices(self, as_of_week: int) -> pd.DataFrame:
        prices = self._dataset.competitor_prices
        visible = prices[prices["week_id"] < as_of_week].sort_values("week_id")
        latest = visible.drop_duplicates(["region", "sku_id"], keep="last")
        return latest.sort_values(["region", "sku_id"]).reset_index(drop=True)

    async def default_as_of_week(self) -> int:
        return int(self._dataset.sales_weekly["week_id"].max()) + 1
