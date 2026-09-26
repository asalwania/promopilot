"""`get_inventory_status`: pooled regional stock per SKU at the as-of week (ADR 0004, 0032).

The inventory for an as-of week is the snapshot at the end of the week before (ADR 0008).
A region pools its stores:

- available stock is Σ (on hand - safety stock), as CONTEXT.md defines it;
- days of cover is Σ on hand ÷ Σ each store's daily demand, where a store's daily demand is
  its on hand ÷ its days of cover in the snapshot (a store with nothing on hand adds none);
- the SKU is overstocked there when that cover exceeds the company-policy threshold.
"""

from typing import Protocol

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from promopilot.agents.tools.as_of import AsOfWeekSource, current_as_of_week
from promopilot.agents.tools.catalogue_filter import in_scope
from promopilot.agents.tools.registry import Tool
from promopilot.domain import CompanyPolicy, Region

DESCRIPTION = (
    "Stock per SKU and region at the as-of week, pooled over the region's stores: units on "
    "hand, safety stock, units on order, available stock (on hand minus safety stock, the "
    "most a promotion may sell), days of cover, and whether the SKU is overstocked there "
    "(days of cover above the company-policy threshold). Filter by regions, categories or "
    "SKU ids, or list only overstocked SKUs."
)


class InventorySource(Protocol):
    """The reads this tool makes (`promopilot.data.RetailData`)."""

    async def products(self) -> pd.DataFrame: ...
    async def stores(self) -> pd.DataFrame: ...
    async def inventory(self, as_of_week: int) -> pd.DataFrame: ...


class GetInventoryStatusInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    regions: list[Region] | None = Field(default=None, description="Omit for every region.")
    categories: list[str] | None = Field(default=None, description="Omit for every category.")
    sku_ids: list[str] | None = Field(default=None, description="Omit for every SKU.")
    overstocked_only: bool = Field(default=False, description="List only overstocked SKUs.")


class InventoryStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    sku_id: str
    region: Region
    on_hand: int
    safety_stock: int
    on_order: int
    available_stock: int
    days_of_cover: float
    is_overstock: bool


class GetInventoryStatusOutput(BaseModel):
    model_config = ConfigDict(frozen=True)

    as_of_week: int
    snapshot_week: int = Field(description="The stock is as at the end of this week.")
    overstock_threshold_days: float
    statuses: list[InventoryStatus]


def get_inventory_status_tool(
    data: InventorySource, as_of_week: AsOfWeekSource, *, policy: CompanyPolicy
) -> Tool[GetInventoryStatusInput, GetInventoryStatusOutput]:
    threshold_days = policy.overstock_threshold_weeks * 7

    async def get_inventory_status(arguments: GetInventoryStatusInput) -> GetInventoryStatusOutput:
        week = await current_as_of_week(as_of_week)
        stores = await data.stores()
        products, regions = in_scope(
            await data.products(),
            sorted(stores["region"].unique()),
            regions=arguments.regions,
            categories=arguments.categories,
            sku_ids=arguments.sku_ids,
        )
        pooled = _pool_by_region(await data.inventory(week), stores)
        wanted = pooled[
            pooled["sku_id"].isin(products["sku_id"])
            & pooled["region"].isin([region.value for region in regions])
        ]
        rank = {region.value: n for n, region in enumerate(Region)}
        wanted = wanted.assign(rank=wanted["region"].map(rank)).sort_values(["sku_id", "rank"])
        wanted = wanted.assign(
            available_stock=wanted["on_hand"] - wanted["safety_stock"],
            is_overstock=wanted["days_of_cover"] > threshold_days,
        )
        if arguments.overstocked_only:
            wanted = wanted[wanted["is_overstock"]]
        statuses = [InventoryStatus.model_validate(row) for row in wanted.to_dict("records")]
        return GetInventoryStatusOutput(
            as_of_week=week,
            snapshot_week=week - 1,
            overstock_threshold_days=threshold_days,
            statuses=statuses,
        )

    return Tool(
        name="get_inventory_status",
        description=DESCRIPTION,
        input_type=GetInventoryStatusInput,
        output_type=GetInventoryStatusOutput,
        handler=get_inventory_status,
    )


def _pool_by_region(snapshot: pd.DataFrame, stores: pd.DataFrame) -> pd.DataFrame:
    stock = snapshot.merge(stores[["store_id", "region"]], on="store_id")
    cover = stock["days_of_cover"]
    stock = stock.assign(
        daily_demand=(stock["on_hand"] / cover.where(cover > 0)).fillna(0.0),
    )
    pooled = (
        stock.groupby(["sku_id", "region"], sort=False)
        .agg(
            on_hand=("on_hand", "sum"),
            safety_stock=("safety_stock", "sum"),
            on_order=("on_order", "sum"),
            daily_demand=("daily_demand", "sum"),
        )
        .reset_index()
    )
    demand = pooled["daily_demand"]
    pooled["days_of_cover"] = (pooled["on_hand"] / demand.where(demand > 0)).fillna(0.0)
    return pooled
