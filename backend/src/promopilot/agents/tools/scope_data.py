"""`get_scope_data`: the regions, categories, subcategories and SKUs a plan may cover.

The catalogue and stores do not change over time, so this tool needs no as-of week.
"""

from typing import Protocol

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from promopilot.agents.tools.catalogue_filter import in_scope
from promopilot.agents.tools.registry import Tool
from promopilot.domain import Region

DESCRIPTION = (
    "List the regions (with their stores and cities) and the product hierarchy (category, "
    "subcategory, SKU with name, brand, pack size, base price and unit cost in rupees, and "
    "whether it is a KVI) that a plan may cover. Filter by regions, categories or SKU ids; "
    "omit a filter to list everything."
)


class ScopeDataSource(Protocol):
    """The catalogue reads this tool makes (`promopilot.data.RetailData`)."""

    async def products(self) -> pd.DataFrame: ...
    async def stores(self) -> pd.DataFrame: ...


class GetScopeDataInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    regions: list[Region] | None = Field(default=None, description="Omit for every region.")
    categories: list[str] | None = Field(default=None, description="Omit for every category.")
    sku_ids: list[str] | None = Field(default=None, description="Omit for every SKU.")


class StoreInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    store_id: str
    city: str


class RegionScope(BaseModel):
    model_config = ConfigDict(frozen=True)

    region: Region
    stores: list[StoreInfo]


class SkuInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    sku_id: str
    name: str
    brand: str
    pack_size: str
    base_price: float
    unit_cost: float
    is_kvi: bool


class SubcategoryScope(BaseModel):
    model_config = ConfigDict(frozen=True)

    subcategory: str
    skus: list[SkuInfo]


class CategoryScope(BaseModel):
    model_config = ConfigDict(frozen=True)

    category: str
    subcategories: list[SubcategoryScope]


class GetScopeDataOutput(BaseModel):
    model_config = ConfigDict(frozen=True)

    regions: list[RegionScope]
    categories: list[CategoryScope]


def get_scope_data_tool(data: ScopeDataSource) -> Tool[GetScopeDataInput, GetScopeDataOutput]:
    async def get_scope_data(arguments: GetScopeDataInput) -> GetScopeDataOutput:
        stores = await data.stores()
        products, regions = in_scope(
            await data.products(),
            sorted(stores["region"].unique()),
            regions=arguments.regions,
            categories=arguments.categories,
            sku_ids=arguments.sku_ids,
        )
        return GetScopeDataOutput(
            regions=[
                RegionScope(
                    region=region,
                    stores=[
                        StoreInfo.model_validate(row)
                        for row in stores[stores["region"] == region.value]
                        .sort_values("store_id")
                        .to_dict("records")
                    ],
                )
                for region in regions
            ],
            categories=[
                CategoryScope(
                    category=str(category),
                    subcategories=[
                        SubcategoryScope(
                            subcategory=str(subcategory),
                            skus=[
                                SkuInfo.model_validate(row)
                                for row in skus.to_dict("records")  # already in SKU order
                            ],
                        )
                        for subcategory, skus in rows.groupby("subcategory", sort=True)
                    ],
                )
                for category, rows in products.groupby("category", sort=True)
            ],
        )

    return Tool(
        name="get_scope_data",
        description=DESCRIPTION,
        input_type=GetScopeDataInput,
        output_type=GetScopeDataOutput,
        handler=get_scope_data,
    )
