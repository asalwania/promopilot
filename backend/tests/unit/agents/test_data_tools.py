"""The scope and data tools: what the planner sees of the world, as of a week (ADR 0032)."""

from typing import Any

import pandas as pd
import pytest
from pydantic import BaseModel

from promopilot.agents.tools import ToolError, ToolOk, ToolRegistry
from promopilot.agents.tools.as_of import AsOfWeekSource, fixed_as_of_week
from promopilot.agents.tools.holidays import GetHolidaysInput, GetHolidaysOutput, get_holidays_tool
from promopilot.agents.tools.inventory_status import (
    GetInventoryStatusInput,
    GetInventoryStatusOutput,
    get_inventory_status_tool,
)
from promopilot.agents.tools.scope_data import (
    GetScopeDataInput,
    GetScopeDataOutput,
    SkuInfo,
    get_scope_data_tool,
)
from promopilot.datagen import GeneratedDataset
from promopilot.domain import CompanyPolicy
from tests.unit.agents.fakes import InMemoryRetailData

AS_OF = 104
"""The default as-of week of the seed-42 world: Diwali 2026 is weeks 108 (lead-in) and 109."""

POLICY = CompanyPolicy()


def registry(data: InMemoryRetailData, as_of: AsOfWeekSource) -> ToolRegistry:
    return ToolRegistry(
        [
            get_scope_data_tool(data),
            get_inventory_status_tool(data, as_of, policy=POLICY),
            get_holidays_tool(data, as_of),
        ]
    )


@pytest.fixture
def data(default_dataset: GeneratedDataset) -> InMemoryRetailData:
    return InMemoryRetailData(default_dataset)


@pytest.fixture
def tools(data: InMemoryRetailData) -> ToolRegistry:
    return registry(data, fixed_as_of_week(AS_OF))


async def call_ok(tools: ToolRegistry, name: str, arguments: dict[str, Any]) -> Any:
    result = await tools.call(name, arguments)
    assert isinstance(result, ToolOk), result
    return result.output


async def call_error(tools: ToolRegistry, name: str, arguments: dict[str, Any]) -> ToolError:
    result = await tools.call(name, arguments)
    assert isinstance(result, ToolError), result
    return result


def test_the_registry_lists_the_data_tools_with_their_schemas(tools: ToolRegistry) -> None:
    specs = {spec.name: spec for spec in tools.specs()}

    assert list(specs) == ["get_scope_data", "get_inventory_status", "get_holidays"]
    schemas: list[tuple[str, type[BaseModel], type[BaseModel]]] = [
        ("get_scope_data", GetScopeDataInput, GetScopeDataOutput),
        ("get_inventory_status", GetInventoryStatusInput, GetInventoryStatusOutput),
        ("get_holidays", GetHolidaysInput, GetHolidaysOutput),
    ]
    for name, input_type, output_type in schemas:
        assert specs[name].input_schema == input_type.model_json_schema()
        assert specs[name].output_schema == output_type.model_json_schema(mode="serialization")
        assert specs[name].description


# get_scope_data


async def test_scope_data_lists_the_categories_subcategories_skus_and_regions_in_scope(
    tools: ToolRegistry, default_dataset: GeneratedDataset
) -> None:
    output = await call_ok(
        tools,
        "get_scope_data",
        {"regions": ["North", "West"], "categories": ["Snacks", "Beverages"]},
    )

    assert isinstance(output, GetScopeDataOutput)
    assert [r.region for r in output.regions] == ["North", "West"]
    stores = default_dataset.stores
    for region in output.regions:
        expected = stores[stores["region"] == region.region.value]
        assert [s.store_id for s in region.stores] == sorted(expected["store_id"])
        assert {s.city for s in region.stores} == set(expected["city"])
    products = default_dataset.products
    in_scope = products[products["category"].isin(["Snacks", "Beverages"])]
    assert [c.category for c in output.categories] == ["Beverages", "Snacks"]
    listed = {
        sku.sku_id: (category.category, sub.subcategory, sku)
        for category in output.categories
        for sub in category.subcategories
        for sku in sub.skus
    }
    assert set(listed) == set(in_scope["sku_id"])
    for row in in_scope.to_dict("records"):
        category, subcategory, sku = listed[str(row["sku_id"])]
        assert (category, subcategory) == (row["category"], row["subcategory"])
        assert sku.model_dump() == {key: row[key] for key in SkuInfo.model_fields}


async def test_scope_data_defaults_to_everything_and_can_narrow_to_skus(
    tools: ToolRegistry, default_dataset: GeneratedDataset
) -> None:
    everything = await call_ok(tools, "get_scope_data", {})
    narrowed = await call_ok(tools, "get_scope_data", {"sku_ids": ["SKU0006", "SKU0002"]})

    assert len(everything.regions) == 4
    assert {c.category for c in everything.categories} == set(default_dataset.products["category"])
    [snacks] = narrowed.categories
    [namkeen] = snacks.subcategories
    assert [sku.sku_id for sku in namkeen.skus] == ["SKU0002", "SKU0006"]


async def test_scope_data_rejects_categories_and_skus_the_catalogue_lacks(
    tools: ToolRegistry,
) -> None:
    error = await call_error(
        tools, "get_scope_data", {"categories": ["Snacks", "Toys"], "sku_ids": ["SKU9999"]}
    )

    assert error.code == "invalid_input"
    assert [(d.loc, d.message) for d in error.details] == [
        ("categories.1", "no category named Toys"),
        ("sku_ids.0", "no SKU with id SKU9999"),
    ]


# get_inventory_status


def pooled_snapshot(dataset: GeneratedDataset, as_of_week: int) -> pd.DataFrame:
    """The ADR 0032 pooling, computed straight from the generated snapshot."""
    stock = dataset.inventory[dataset.inventory["snapshot_week"] == as_of_week - 1]
    stock = stock.merge(dataset.stores[["store_id", "region"]], on="store_id")
    stock = stock.assign(
        available=stock["on_hand"] - stock["safety_stock"],
        daily_demand=stock["on_hand"] / stock["days_of_cover"],
    )
    pooled = stock.groupby(["sku_id", "region"]).agg(
        on_hand=("on_hand", "sum"),
        available=("available", "sum"),
        daily_demand=("daily_demand", "sum"),
    )
    pooled["days_of_cover"] = pooled["on_hand"] / pooled["daily_demand"]
    return pooled


async def test_inventory_status_pools_the_as_of_week_snapshot_per_sku_and_region(
    tools: ToolRegistry, data: InMemoryRetailData, default_dataset: GeneratedDataset
) -> None:
    output = await call_ok(
        tools,
        "get_inventory_status",
        {"regions": ["North", "West"], "categories": ["Snacks"]},
    )

    assert isinstance(output, GetInventoryStatusOutput)
    assert (output.as_of_week, output.snapshot_week) == (AS_OF, AS_OF - 1)
    assert output.overstock_threshold_days == POLICY.overstock_threshold_weeks * 7
    assert data.inventory_as_of_weeks == [AS_OF]
    expected = pooled_snapshot(default_dataset, AS_OF)
    products = default_dataset.products
    snacks = set(products[products["category"] == "Snacks"]["sku_id"])
    assert {(s.sku_id, s.region.value) for s in output.statuses} == {
        (sku, region) for sku in snacks for region in ("North", "West")
    }
    for status in output.statuses:
        key = (status.sku_id, status.region.value)
        assert status.on_hand == expected.at[key, "on_hand"]
        assert status.available_stock == expected.at[key, "available"]
        assert status.days_of_cover == pytest.approx(expected.at[key, "days_of_cover"])
        assert status.is_overstock == (status.days_of_cover > output.overstock_threshold_days)


async def test_the_demo_briefs_namkeen_packs_are_overstocked_in_north_and_west(
    tools: ToolRegistry,
) -> None:
    output = await call_ok(
        tools,
        "get_inventory_status",
        {"regions": ["North", "West"], "sku_ids": ["SKU0002", "SKU0006"]},
    )

    assert [(s.sku_id, s.region.value, s.is_overstock) for s in output.statuses] == [
        ("SKU0002", "North", True),
        ("SKU0002", "West", True),
        ("SKU0006", "North", True),
        ("SKU0006", "West", True),
    ]


async def test_inventory_status_can_list_only_overstocked_skus(tools: ToolRegistry) -> None:
    output = await call_ok(tools, "get_inventory_status", {"overstocked_only": True})

    assert output.statuses
    assert all(status.is_overstock for status in output.statuses)
    assert {"SKU0002", "SKU0006"} <= {status.sku_id for status in output.statuses}


async def test_inventory_status_reads_the_snapshot_before_the_bound_as_of_week(
    data: InMemoryRetailData, default_dataset: GeneratedDataset
) -> None:
    tools = registry(data, fixed_as_of_week(80))

    output = await call_ok(tools, "get_inventory_status", {"sku_ids": ["SKU0010"]})

    assert data.inventory_as_of_weeks == [80]
    assert output.snapshot_week == 79
    expected = pooled_snapshot(default_dataset, 80)
    for status in output.statuses:
        assert status.on_hand == expected.loc[(status.sku_id, status.region.value), "on_hand"]


async def test_the_as_of_week_is_resolved_on_every_call(data: InMemoryRetailData) -> None:
    weeks = iter([90, 104])

    async def moving_clock() -> int:
        return next(weeks)

    tools = registry(data, moving_clock)

    first = await call_ok(tools, "get_inventory_status", {"sku_ids": ["SKU0010"]})
    second = await call_ok(tools, "get_inventory_status", {"sku_ids": ["SKU0010"]})

    assert (first.as_of_week, second.as_of_week) == (90, 104)


async def test_no_loaded_data_is_a_data_unavailable_error(data: InMemoryRetailData) -> None:
    async def no_history() -> int:
        raise LookupError("no sales history is loaded; run `make data`")

    tools = registry(data, no_history)

    for name, arguments in [
        ("get_inventory_status", {}),
        ("get_holidays", {"start_week": 105, "end_week": 110}),
    ]:
        error = await call_error(tools, name, arguments)
        assert error.code == "data_unavailable"
        assert "make data" in error.message


async def test_inventory_status_rejects_unknown_skus_and_categories(tools: ToolRegistry) -> None:
    error = await call_error(
        tools, "get_inventory_status", {"sku_ids": ["SKU9999"], "categories": ["Toys"]}
    )

    assert error.code == "invalid_input"
    assert [d.loc for d in error.details] == ["categories.0", "sku_ids.0"]


# get_holidays


async def test_holidays_lists_national_and_regional_holidays_with_intensity(
    tools: ToolRegistry,
) -> None:
    output = await call_ok(
        tools,
        "get_holidays",
        {"regions": ["North", "East"], "start_week": 105, "end_week": 110},
    )

    assert isinstance(output, GetHolidaysOutput)
    assert output.as_of_week == AS_OF
    rows = [
        (h.holiday, h.region.value, h.week_id, h.intensity, h.national) for h in output.holidays
    ]
    assert rows == [
        ("Durga Puja", "East", 106, 0.45, False),
        ("Durga Puja", "East", 107, 0.9, False),
        ("Diwali", "North", 108, 0.5, True),
        ("Diwali", "East", 108, 0.5, True),
        ("Diwali", "North", 109, 1.0, True),
        ("Diwali", "East", 109, 1.0, True),
    ]
    assert str(output.holidays[-1].week_start) == "2026-11-02"


async def test_holidays_default_to_every_region(tools: ToolRegistry) -> None:
    output = await call_ok(tools, "get_holidays", {"start_week": 109, "end_week": 109})

    assert [h.region.value for h in output.holidays] == ["North", "South", "East", "West"]


@pytest.mark.parametrize(
    ("start_week", "end_week", "message"),
    [
        (104, 110, "after the as-of week 104"),
        (90, 95, "after the as-of week 104"),
        (150, 170, "the calendar ends at week 155"),
    ],
)
async def test_holidays_are_only_listed_for_windows_after_the_as_of_week_within_the_calendar(
    tools: ToolRegistry, start_week: int, end_week: int, message: str
) -> None:
    error = await call_error(
        tools, "get_holidays", {"start_week": start_week, "end_week": end_week}
    )

    assert error.code == "invalid_input"
    assert message in error.message


async def test_a_window_ending_before_it_starts_breaks_the_input_schema(
    tools: ToolRegistry,
) -> None:
    error = await call_error(tools, "get_holidays", {"start_week": 110, "end_week": 108})

    assert error.code == "invalid_input"
