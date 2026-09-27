"""`compare_mechanisms` through the tool registry: each mechanism's best option for one SKU in
one region, on the fitted small world (ADR 0041)."""

from typing import Any

import pytest

from promopilot.agents.tools import ToolError, ToolOk, ToolRegistry
from promopilot.agents.tools.as_of import fixed_as_of_week
from promopilot.agents.tools.compare_mechanisms import (
    CompareMechanismsInput,
    CompareMechanismsOutput,
    compare_mechanisms_tool,
)
from promopilot.datagen import GeneratedDataset
from promopilot.domain import CompanyPolicy, Mechanism, Region
from promopilot.models.demand import DemandHistory, DemandModel
from promopilot.models.registry import ModelKind
from promopilot.models.relations import Relations
from tests.conftest import SMALL_AS_OF
from tests.unit.agents.fakes import InMemoryRetailData
from tests.unit.agents.test_generate_candidates import Fixed, entry


def build(
    small_models: tuple[DemandModel, Relations],
    small_dataset: GeneratedDataset,
    *,
    demand: bool = True,
    relations: bool = True,
) -> ToolRegistry:
    model, found = small_models
    return ToolRegistry(
        [
            compare_mechanisms_tool(
                Fixed((entry(ModelKind.DEMAND, 3), model) if demand else None),
                Fixed((entry(ModelKind.RELATIONS, 2), found) if relations else None),
                InMemoryRetailData(small_dataset),
                fixed_as_of_week(SMALL_AS_OF),
                policy=CompanyPolicy(),
            )
        ]
    )


@pytest.fixture
def tools(
    small_models: tuple[DemandModel, Relations], small_dataset: GeneratedDataset
) -> ToolRegistry:
    return build(small_models, small_dataset)


def with_complement(small_models: tuple[DemandModel, Relations], products: Any) -> str:
    """A SKU of the first category that has a detected complement."""
    category = sorted(products["category"].unique())[0]
    for sku_id in sorted(products.loc[products["category"] == category, "sku_id"]):
        if not small_models[1].complements(sku_id).empty:
            return str(sku_id)
    raise AssertionError("the small world has no complement in its first category")


def arguments(small_history: DemandHistory, sku_id: str, **changes: Any) -> dict[str, Any]:
    category = sorted(small_history.products["category"].unique())[0]
    request = {
        "as_of_week": SMALL_AS_OF,
        "scope": {"regions": ["North", "South"], "categories": [category]},
        "promo_window": {"start_week": SMALL_AS_OF + 1, "end_week": SMALL_AS_OF + 2},
        "marketing_budget": 200_000.0,
    }
    return {
        "request": request | changes.pop("request", {}),
        "sku_id": sku_id,
        "region": "North",
        **changes,
    }


def test_the_registry_lists_compare_mechanisms_with_its_schemas(tools: ToolRegistry) -> None:
    [spec] = tools.specs()

    assert spec.name == "compare_mechanisms"
    assert spec.input_schema == CompareMechanismsInput.model_json_schema()
    assert spec.output_schema == CompareMechanismsOutput.model_json_schema(mode="serialization")


async def test_a_call_compares_every_mechanism_for_the_sku_in_the_region(
    tools: ToolRegistry,
    small_models: tuple[DemandModel, Relations],
    small_history: DemandHistory,
) -> None:
    sku_id = with_complement(small_models, small_history.products)

    result = await tools.call("compare_mechanisms", arguments(small_history, sku_id))

    assert isinstance(result, ToolOk), result
    output = result.output
    assert isinstance(output, CompareMechanismsOutput)
    assert CompareMechanismsOutput.model_validate(output.model_dump(mode="json")) == output
    assert (output.sku_id, output.region) == (sku_id, Region.NORTH)
    assert output.demand_model.version == 3
    assert output.relations_model.version == 2
    assert output.as_of_week == SMALL_AS_OF
    mechanisms = [outcome.mechanism for outcome in output.outcomes]
    assert len(mechanisms) == len(set(mechanisms))
    assert Mechanism.BUNDLE in mechanisms
    complements = set(small_models[1].complements(sku_id)["sku_id"])
    for outcome in output.outcomes:
        assert outcome.chosen is False
        if outcome.best is None:
            assert outcome.unavailable
            continue
        option = outcome.best.option
        assert (option.sku_id, option.region, option.mechanism) == (
            sku_id,
            Region.NORTH,
            outcome.mechanism,
        )
        if outcome.mechanism is Mechanism.BUNDLE:
            assert option.bundle_partner_sku_id in complements
            assert outcome.best.basket_lift is not None
            assert outcome.best.basket_lift > 1.5
    values = [outcome.best.value for outcome in output.outcomes if outcome.best is not None]
    assert values == sorted(values, reverse=True)


async def test_the_same_call_gives_the_same_comparison(
    tools: ToolRegistry,
    small_models: tuple[DemandModel, Relations],
    small_history: DemandHistory,
) -> None:
    call = arguments(small_history, with_complement(small_models, small_history.products))

    first = await tools.call("compare_mechanisms", call)
    again = await tools.call("compare_mechanisms", call)

    assert isinstance(first, ToolOk)
    assert isinstance(again, ToolOk)
    assert first.output == again.output


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"request": {"as_of_week": SMALL_AS_OF - 1}}, "as-of week"),
        ({"region": "East"}, "scope"),
        ({"request": {"scope": {"regions": ["North"], "categories": ["Nope"]}}}, "data lacks"),
    ],
)
async def test_calls_the_data_cannot_answer_are_invalid_input(
    tools: ToolRegistry,
    small_models: tuple[DemandModel, Relations],
    small_history: DemandHistory,
    changes: dict[str, Any],
    message: str,
) -> None:
    sku_id = with_complement(small_models, small_history.products)

    result = await tools.call("compare_mechanisms", arguments(small_history, sku_id, **changes))

    assert isinstance(result, ToolError)
    assert result.code == "invalid_input"
    assert message in result.message


async def test_a_sku_outside_the_requests_scope_is_invalid_input(
    tools: ToolRegistry, small_history: DemandHistory
) -> None:
    products = small_history.products
    category = sorted(products["category"].unique())[0]
    outside = str(products.loc[products["category"] != category, "sku_id"].iloc[0])

    for sku_id in (outside, "NOPE"):
        result = await tools.call("compare_mechanisms", arguments(small_history, sku_id))

        assert isinstance(result, ToolError)
        assert result.code == "invalid_input"
        assert sku_id in result.message


@pytest.mark.parametrize("missing", ["demand", "relations"])
async def test_a_missing_model_is_model_unavailable(
    small_models: tuple[DemandModel, Relations],
    small_dataset: GeneratedDataset,
    small_history: DemandHistory,
    missing: str,
) -> None:
    tools = build(small_models, small_dataset, **{missing: False})
    sku_id = with_complement(small_models, small_history.products)

    result = await tools.call("compare_mechanisms", arguments(small_history, sku_id))

    assert isinstance(result, ToolError)
    assert result.code == "model_unavailable"
