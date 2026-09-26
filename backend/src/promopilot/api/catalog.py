"""The catalogue and stock over HTTP, for the `/data` explorer (SPEC §10, ADR 0034).

- `GET /api/catalog/products`: the products, filtered by category and KVI flag.
- `GET /api/catalog/regions`: each region's stores with their segment mix.
- `GET /api/inventory`: pooled regional stock with overstock flags, as `get_inventory_status`
  computes it (ADR 0032), plus each SKU's name and category. A person may look at any as-of
  week; it defaults to the data's default as-of week (ADR 0008).

The filters and pooling are the data tools' own, so the explorer shows what the planner sees.
"""

from collections.abc import Awaitable
from typing import Annotated, Protocol

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict

from promopilot.agents.tools import ToolCallError
from promopilot.agents.tools.as_of import fixed_as_of_week
from promopilot.agents.tools.inventory_status import (
    GetInventoryStatusInput,
    InventorySource,
    InventoryStatus,
    get_inventory_status_tool,
)
from promopilot.agents.tools.scope_data import GetScopeDataInput, get_scope_data_tool
from promopilot.domain import CompanyPolicy, Region, Segment


class CatalogSource(InventorySource, Protocol):
    """`promopilot.data.RetailData`: the catalogue, stores, stock and default as-of week."""

    async def default_as_of_week(self) -> int: ...


class Product(BaseModel):
    model_config = ConfigDict(frozen=True)

    sku_id: str
    name: str
    brand: str
    category: str
    subcategory: str
    pack_size: str
    base_price: float
    unit_cost: float
    is_kvi: bool


class ProductList(BaseModel):
    model_config = ConfigDict(frozen=True)

    products: list[Product]


class Store(BaseModel):
    model_config = ConfigDict(frozen=True)

    store_id: str
    city: str
    segment_mix: dict[Segment, float]


class RegionStores(BaseModel):
    model_config = ConfigDict(frozen=True)

    region: Region
    stores: list[Store]


class RegionList(BaseModel):
    model_config = ConfigDict(frozen=True)

    regions: list[RegionStores]


class InventoryRow(InventoryStatus):
    name: str
    category: str


class InventoryReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    as_of_week: int
    snapshot_week: int
    overstock_threshold_days: float
    statuses: list[InventoryRow]


class NoDataError(Exception):
    """No data is loaded, or none for the asked week."""


class CatalogService:
    def __init__(self, data: CatalogSource, *, policy: CompanyPolicy) -> None:
        self._data = data
        self._policy = policy

    async def products(self, *, category: str | None = None, kvi_only: bool = False) -> ProductList:
        """Raises `ValueError` for an unknown category."""
        scope = await _answer(
            get_scope_data_tool(self._data).handler(
                GetScopeDataInput(categories=None if category is None else [category])
            )
        )
        products = [
            Product(
                category=category_scope.category,
                subcategory=subcategory.subcategory,
                **sku.model_dump(),
            )
            for category_scope in scope.categories
            for subcategory in category_scope.subcategories
            for sku in subcategory.skus
            if sku.is_kvi or not kvi_only
        ]
        return ProductList(products=sorted(products, key=lambda product: product.sku_id))

    async def regions(self) -> RegionList:
        stores = await self._data.stores()
        return RegionList(
            regions=[
                RegionStores(
                    region=region,
                    stores=[
                        Store.model_validate(row)
                        for row in stores[stores["region"] == region.value]
                        .sort_values("store_id")
                        .to_dict("records")
                    ],
                )
                for region in Region
                if (stores["region"] == region.value).any()
            ]
        )

    async def inventory(
        self,
        *,
        as_of_week: int | None = None,
        region: Region | None = None,
        category: str | None = None,
        overstocked_only: bool = False,
    ) -> InventoryReport:
        """Raises `NoDataError` without data at the week, `ValueError` for an unknown filter."""
        try:
            week = as_of_week if as_of_week is not None else await self._data.default_as_of_week()
            tool = get_inventory_status_tool(
                self._data, fixed_as_of_week(week), policy=self._policy
            )
            status = await _answer(
                tool.handler(
                    GetInventoryStatusInput(
                        regions=None if region is None else [region],
                        categories=None if category is None else [category],
                        overstocked_only=overstocked_only,
                    )
                )
            )
        except LookupError as error:
            raise NoDataError(str(error)) from error
        names = (await self._data.products()).set_index("sku_id")[["name", "category"]]
        return InventoryReport(
            as_of_week=status.as_of_week,
            snapshot_week=status.snapshot_week,
            overstock_threshold_days=status.overstock_threshold_days,
            statuses=[
                InventoryRow(**row.model_dump(), **_product_names(names, row.sku_id))
                for row in status.statuses
            ],
        )


async def _answer[T](call: Awaitable[T]) -> T:
    """A tool's answer; a call naming things the data lacks becomes a `ValueError`."""
    try:
        return await call
    except ToolCallError as error:
        details = "; ".join(detail.message for detail in error.error.details)
        raise ValueError(details or error.error.message) from error


def _product_names(names: pd.DataFrame, sku_id: str) -> dict[str, str]:
    return {"name": str(names.at[sku_id, "name"]), "category": str(names.at[sku_id, "category"])}


def catalog_router(catalog: CatalogService) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["catalog"])

    @router.get("/catalog/products")
    async def list_products(category: str | None = None, kvi_only: bool = False) -> ProductList:
        """Every product in SKU order; an unknown category is 422."""
        try:
            return await catalog.products(category=category, kvi_only=kvi_only)
        except ValueError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error

    @router.get("/catalog/regions")
    async def list_regions() -> RegionList:
        """Each region's stores with their customer segment mix."""
        return await catalog.regions()

    @router.get(
        "/inventory",
        responses={status.HTTP_409_CONFLICT: {"description": "No data is loaded for the week"}},
    )
    async def inventory(
        as_of_week: Annotated[
            int | None, Query(ge=0, description="Defaults to the data's default as-of week.")
        ] = None,
        region: Region | None = None,
        category: str | None = None,
        overstocked_only: bool = False,
    ) -> InventoryReport:
        """Stock per SKU x region pooled over the region's stores, with overstock flags.

        An unknown category, or a region without stores, is 422.
        """
        try:
            return await catalog.inventory(
                as_of_week=as_of_week,
                region=region,
                category=category,
                overstocked_only=overstocked_only,
            )
        except NoDataError as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
        except ValueError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error

    return router
