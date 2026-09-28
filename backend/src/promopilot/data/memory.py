"""Read access to a generated dataset's tables held in memory, as `RetailData` reads Postgres
(ADR 0008, ADR 0056).

The eval harness plans each scenario on its own in-memory world, and tests plan on a small
generated one. Only the data tables are read: whatever else the source holds, the ground truth
included, is never touched here.
"""

import json
from typing import Protocol

import pandas as pd


class RetailTables(Protocol):
    """The data tables of a generated dataset (`promopilot.datagen.GeneratedDataset`)."""

    @property
    def products(self) -> pd.DataFrame: ...
    @property
    def stores(self) -> pd.DataFrame: ...
    @property
    def calendar(self) -> pd.DataFrame: ...
    @property
    def sales_weekly(self) -> pd.DataFrame: ...
    @property
    def inventory(self) -> pd.DataFrame: ...
    @property
    def competitor_prices(self) -> pd.DataFrame: ...


class InMemoryRetailData:
    """Answers the as-of-week queries a planning session makes, like Postgres would.

    With `as_of_week` the clock is fixed there (an eval scenario's week); without it, it is the
    first week after the sales history, as `RetailData.default_as_of_week` says.
    """

    def __init__(self, tables: RetailTables, *, as_of_week: int | None = None) -> None:
        self._tables = tables
        self._as_of_week = as_of_week

    async def default_as_of_week(self) -> int:
        if self._as_of_week is not None:
            return self._as_of_week
        return int(self._tables.sales_weekly["week_id"].max()) + 1

    async def inventory(self, as_of_week: int) -> pd.DataFrame:
        stock = self._tables.inventory
        snapshot = stock[stock["snapshot_week"] == as_of_week - 1]
        if snapshot.empty:
            raise LookupError(f"no inventory snapshot for the end of week {as_of_week - 1}")
        return snapshot.sort_values(["store_id", "sku_id"]).reset_index(drop=True)

    async def products(self) -> pd.DataFrame:
        return self._tables.products.sort_values("sku_id").reset_index(drop=True)

    async def stores(self) -> pd.DataFrame:
        return self._tables.stores.sort_values("store_id").reset_index(drop=True)

    async def calendar(self) -> pd.DataFrame:
        """The festival calendar, past and future: holidays are known in advance."""
        frame = self._tables.calendar.sort_values(["region", "week_id"])
        return frame.reset_index(drop=True)

    async def sales_history(
        self, as_of_week: int, *, since_week: int | None = None
    ) -> pd.DataFrame:
        sales = self._tables.sales_weekly
        visible = sales[
            (sales["week_id"] < as_of_week) & (sales["week_id"] >= (since_week or 0))
        ].copy()
        # Postgres returns the JSONB column already decoded.
        visible["segment_units"] = visible["segment_units"].map(json.loads)
        return visible.reset_index(drop=True)

    async def latest_competitor_prices(self, as_of_week: int) -> pd.DataFrame:
        """Per region and SKU, the competitor's last price before the as-of week."""
        prices = self._tables.competitor_prices
        visible = prices[prices["week_id"] < as_of_week].sort_values("week_id")
        latest = visible.drop_duplicates(["region", "sku_id"], keep="last")
        return latest.sort_values(["region", "sku_id"]).reset_index(drop=True)
