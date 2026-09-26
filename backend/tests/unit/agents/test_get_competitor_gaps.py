"""`get_competitor_gaps` through the tool registry (SPEC §9.6, ADR 0025, ADR 0031)."""

import pandas as pd
import pytest

from promopilot.agents.tools import ToolError, ToolOk, ToolRegistry
from promopilot.agents.tools.as_of import fixed_as_of_week
from promopilot.agents.tools.get_competitor_gaps import (
    GetCompetitorGapsInput,
    get_competitor_gaps_tool,
)
from promopilot.competitors import CompetitorGaps
from promopilot.domain import CompanyPolicy

AS_OF = 20

PRODUCTS = pd.DataFrame(
    [
        ("K1", "Atta 5kg", "Staples", "Flour", 100.0, True),
        ("K2", "Rice 5kg", "Staples", "Rice", 100.0, True),
        ("N1", "Namkeen 400g", "Snacks", "Namkeen", 50.0, False),
    ],
    columns=["sku_id", "name", "category", "subcategory", "base_price", "is_kvi"],
).assign(brand="B", pack_size="1", unit_cost=30.0)

PRICES = pd.DataFrame(
    [
        (AS_OF - 1, "North", "K1", 95.1, False),  # a 4.9% gap
        (AS_OF - 1, "North", "K2", 94.9, True),  # a 5.1% gap
        (AS_OF - 1, "South", "N1", 45.0, True),
        (AS_OF, "North", "K1", 60.0, True),  # the future: never visible
        (AS_OF + 3, "West", "K2", 60.0, True),
    ],
    columns=["week_id", "region", "sku_id", "competitor_price", "competitor_on_promo"],
)


class LeakyData:
    """A data source that returns every competitor price, even future ones."""

    def __init__(self) -> None:
        self.asked_for: list[int] = []

    async def products(self) -> pd.DataFrame:
        return PRODUCTS

    async def latest_competitor_prices(self, as_of_week: int) -> pd.DataFrame:
        self.asked_for.append(as_of_week)
        return PRICES


async def no_data() -> int:
    raise LookupError("no sales history is loaded; run `make data`")


@pytest.fixture
def data() -> LeakyData:
    return LeakyData()


@pytest.fixture
def tools(data: LeakyData) -> ToolRegistry:
    return ToolRegistry(
        [get_competitor_gaps_tool(data, fixed_as_of_week(AS_OF), policy=CompanyPolicy())]
    )


def test_the_registry_lists_get_competitor_gaps_with_its_schemas(tools: ToolRegistry) -> None:
    [spec] = tools.specs()

    assert spec.name == "get_competitor_gaps"
    assert spec.input_schema == GetCompetitorGapsInput.model_json_schema()
    assert spec.output_schema == CompetitorGaps.model_json_schema(mode="serialization")
    assert set(spec.input_schema["properties"]) == {"regions", "categories", "sku_ids", "kvi_only"}


async def test_schema_valid_output_flags_5_1_pct_but_not_4_9_pct_at_the_bound_week(
    tools: ToolRegistry, data: LeakyData
) -> None:
    result = await tools.call("get_competitor_gaps", {"regions": ["North"], "kvi_only": True})

    assert isinstance(result, ToolOk)
    # What the LLM receives parses back under the output schema the registry lists.
    output = CompetitorGaps.model_validate(result.model_dump(mode="json")["output"])
    assert output.as_of_week == AS_OF
    assert data.asked_for == [AS_OF]
    assert [(gap.sku_id, gap.undercut) for gap in output.gaps] == [("K2", True), ("K1", False)]


async def test_future_competitor_prices_are_invisible(tools: ToolRegistry) -> None:
    result = await tools.call("get_competitor_gaps", {})

    assert isinstance(result, ToolOk)
    assert isinstance(result.output, CompetitorGaps)
    k1 = next(gap for gap in result.output.gaps if gap.sku_id == "K1")
    assert k1.competitor_price == 95.1
    assert all(gap.region != "West" for gap in result.output.gaps)
    assert all(gap.price_week < AS_OF for gap in result.output.gaps)


async def test_the_llm_cannot_move_the_clock(tools: ToolRegistry) -> None:
    result = await tools.call("get_competitor_gaps", {"as_of_week": AS_OF + 10})

    assert isinstance(result, ToolError)
    assert result.code == "invalid_input"
    assert [detail.loc for detail in result.details] == ["as_of_week"]


@pytest.mark.parametrize(
    ("arguments", "loc"),
    [({"regions": ["Mars"]}, "regions.0"), ({"regions": []}, "regions")],
)
async def test_schema_breaking_filters_are_invalid_input(
    tools: ToolRegistry, arguments: dict[str, object], loc: str
) -> None:
    result = await tools.call("get_competitor_gaps", arguments)

    assert isinstance(result, ToolError)
    assert result.code == "invalid_input"
    assert [detail.loc for detail in result.details] == [loc]


async def test_an_unknown_sku_is_invalid_input_naming_it(tools: ToolRegistry) -> None:
    result = await tools.call("get_competitor_gaps", {"sku_ids": ["K1", "NOPE"]})

    assert isinstance(result, ToolError)
    assert result.code == "invalid_input"
    assert "NOPE" in result.message


async def test_without_loaded_data_the_call_is_data_unavailable(data: LeakyData) -> None:
    tools = ToolRegistry([get_competitor_gaps_tool(data, no_data, policy=CompanyPolicy())])

    result = await tools.call("get_competitor_gaps", {})

    assert isinstance(result, ToolError)
    assert result.code == "data_unavailable"
    assert "make data" in result.message
