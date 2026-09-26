"""Read access to the retail data, as of a week (ADR 0008).

Every time-dependent query takes the as-of week explicitly and never returns sales,
promotions, baskets or competitor prices at or after it. Inventory for an as-of week is
the snapshot at the end of the week before.
"""

from collections.abc import Sequence

import pandas as pd
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from promopilot.data.schema import (
    baskets,
    calendar,
    competitor_prices,
    inventory,
    products,
    promotions_history,
    sales_weekly,
    stores,
)
from promopilot.domain import Region


class RetailData:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def default_as_of_week(self) -> int:
        """The first week after the sales history (ADR 0008)."""
        async with self._engine.connect() as connection:
            last = (await connection.execute(select(func.max(sales_weekly.c.week_id)))).scalar()
        if last is None:
            raise LookupError("no sales history is loaded; run `make data`")
        return int(last) + 1

    async def products(self) -> pd.DataFrame:
        return await self._frame(select(products).order_by(products.c.sku_id))

    async def stores(self, region: Region | None = None) -> pd.DataFrame:
        query = select(stores).order_by(stores.c.store_id)
        if region is not None:
            query = query.where(stores.c.region == region.value)
        return await self._frame(query)

    async def calendar(self, region: Region | None = None) -> pd.DataFrame:
        """The festival calendar, past and future: holidays are known in advance."""
        query = select(calendar).order_by(calendar.c.region, calendar.c.week_id)
        if region is not None:
            query = query.where(calendar.c.region == region.value)
        return await self._frame(query)

    async def sales_history(
        self,
        as_of_week: int,
        *,
        region: Region | None = None,
        sku_ids: Sequence[str] | None = None,
        since_week: int | None = None,
    ) -> pd.DataFrame:
        query = select(sales_weekly).where(sales_weekly.c.week_id < as_of_week)
        if since_week is not None:
            query = query.where(sales_weekly.c.week_id >= since_week)
        if region is not None:
            in_region = select(stores.c.store_id).where(stores.c.region == region.value)
            query = query.where(sales_weekly.c.store_id.in_(in_region))
        if sku_ids is not None:
            query = query.where(sales_weekly.c.sku_id.in_(sku_ids))
        order = (sales_weekly.c.week_id, sales_weekly.c.store_id, sales_weekly.c.sku_id)
        return await self._frame(query.order_by(*order))

    async def promotions_history(
        self,
        as_of_week: int,
        *,
        region: Region | None = None,
        sku_ids: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        """Promotions started before the as-of week, with durations cut at it."""
        visible = func.least(
            promotions_history.c.duration, as_of_week - promotions_history.c.start_week
        )
        columns = [c for c in promotions_history.c if c.name != "duration"]
        query = select(*columns, visible.label("duration")).where(
            promotions_history.c.start_week < as_of_week
        )
        if region is not None:
            query = query.where(promotions_history.c.region == region.value)
        if sku_ids is not None:
            query = query.where(promotions_history.c.sku_id.in_(sku_ids))
        return await self._frame(query.order_by(promotions_history.c.promo_id))

    async def inventory(
        self,
        as_of_week: int,
        *,
        region: Region | None = None,
        sku_ids: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        snapshot = as_of_week - 1
        query = select(inventory).where(inventory.c.snapshot_week == snapshot)
        if region is not None:
            in_region = select(stores.c.store_id).where(stores.c.region == region.value)
            query = query.where(inventory.c.store_id.in_(in_region))
        if sku_ids is not None:
            query = query.where(inventory.c.sku_id.in_(sku_ids))
        frame = await self._frame(query.order_by(inventory.c.store_id, inventory.c.sku_id))
        if frame.empty:
            raise LookupError(f"no inventory snapshot for the end of week {snapshot}")
        return frame

    async def competitor_prices(
        self,
        as_of_week: int,
        *,
        region: Region | None = None,
        sku_ids: Sequence[str] | None = None,
        since_week: int | None = None,
    ) -> pd.DataFrame:
        query = select(competitor_prices).where(competitor_prices.c.week_id < as_of_week)
        if since_week is not None:
            query = query.where(competitor_prices.c.week_id >= since_week)
        if region is not None:
            query = query.where(competitor_prices.c.region == region.value)
        if sku_ids is not None:
            query = query.where(competitor_prices.c.sku_id.in_(sku_ids))
        order = (
            competitor_prices.c.week_id,
            competitor_prices.c.region,
            competitor_prices.c.sku_id,
        )
        return await self._frame(query.order_by(*order))

    async def baskets(self, as_of_week: int, *, since_week: int | None = None) -> pd.DataFrame:
        query = select(baskets).where(baskets.c.week_id < as_of_week)
        if since_week is not None:
            query = query.where(baskets.c.week_id >= since_week)
        return await self._frame(query.order_by(baskets.c.basket_id))

    async def _frame(self, query: Select[tuple[object, ...]]) -> pd.DataFrame:
        async with self._engine.connect() as connection:
            result = await connection.execute(query)
            return pd.DataFrame(result.fetchall(), columns=list(result.keys()))
