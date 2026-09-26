"""`estimate_demand` through the tool registry: the planner's only route to the demand model."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from promopilot.agents.tools import ToolError, ToolOk, ToolRegistry
from promopilot.agents.tools.estimate_demand import (
    EstimateDemandInput,
    EstimateDemandOutput,
    OptionEstimate,
    estimate_demand_tool,
)
from promopilot.domain import CompanyPolicy, Mechanism, PlanLine, Region
from promopilot.models import demand
from promopilot.models.demand import DemandHistory, DemandModel, PredictionContext
from promopilot.models.registry import ModelKind, RegisteredModel

AS_OF = 52
START = 54
POLICY = CompanyPolicy(fixed_cost_per_line_week={mechanism: 1500.0 for mechanism in Mechanism})


class FixedModel:
    """A model source with one registered model, or none."""

    def __init__(self, loaded: tuple[RegisteredModel, DemandModel] | None) -> None:
        self.loaded = loaded

    async def get(self) -> tuple[RegisteredModel, DemandModel] | None:
        return self.loaded


@pytest.fixture(scope="module")
def model(small_history: DemandHistory) -> DemandModel:
    return demand.fit(small_history, as_of_week=AS_OF, seed=7)


@pytest.fixture(scope="module")
def entry(model: DemandModel) -> RegisteredModel:
    return RegisteredModel(
        model_id=uuid4(),
        kind=ModelKind.DEMAND,
        version=3,
        trained_at=datetime(2026, 9, 26, tzinfo=UTC),
        as_of_week=model.as_of_week,
        metrics=model.metrics,
        artifact_path="demand-v3.pkl",
    )


@pytest.fixture(scope="module")
def skus(small_history: DemandHistory) -> list[str]:
    return list(small_history.products["sku_id"])


@pytest.fixture
def tools(entry: RegisteredModel, model: DemandModel) -> ToolRegistry:
    return ToolRegistry([estimate_demand_tool(FixedModel((entry, model)), policy=POLICY)])


def option(sku_id: str, /, **changes: Any) -> dict[str, Any]:
    """A promo option as the LLM sends it: plain JSON."""
    return {
        "sku_id": sku_id,
        "region": "North",
        "mechanism": "PCT_OFF",
        "depth_pct": 20,
        "duration_weeks": 2,
        "start_week": START,
        "target_segment": "All customers",
    } | changes


def test_the_registry_lists_estimate_demand_with_its_schemas(tools: ToolRegistry) -> None:
    [spec] = tools.specs()

    assert spec.name == "estimate_demand"
    assert spec.input_schema == EstimateDemandInput.model_json_schema()
    assert spec.output_schema == EstimateDemandOutput.model_json_schema(mode="serialization")
    assert spec.input_schema["properties"]["options"]["maxItems"] == 200


async def test_schema_valid_input_gives_schema_valid_output_consistent_with_predict(
    tools: ToolRegistry, model: DemandModel, entry: RegisteredModel, skus: list[str]
) -> None:
    options = [
        option(skus[0]),
        option(skus[1], mechanism="BOGO", depth_pct=50, target_segment="Families"),
        option(skus[2], mechanism="BUNDLE", bundle_partner_sku_id=skus[3], region="South"),
    ]

    result = await tools.call("estimate_demand", {"options": options})

    assert isinstance(result, ToolOk)
    # What the LLM receives parses back under the output schema the registry lists.
    output = EstimateDemandOutput.model_validate(result.model_dump(mode="json")["output"])
    assert output.model.model_id == entry.model_id
    assert output.model.version == 3
    assert output.model.as_of_week == AS_OF
    lines = [PlanLine.model_validate(one) for one in options]
    expected = model.predict(lines, PredictionContext(policy=POLICY))
    assert [estimate.option for estimate in output.estimates] == lines
    for n, estimate in enumerate(output.estimates):
        row = expected.options.iloc[n]
        for column in expected.options.columns.intersection(list(OptionEstimate.model_fields)):
            assert getattr(estimate, column) == pytest.approx(row[column], rel=1e-12)
        segments = expected.segments[expected.segments["option"] == n]
        assert [s.segment.value for s in estimate.segments] == list(segments["segment"])
        assert [s.units for s in estimate.segments] == pytest.approx(list(segments["units"]))
        assert [s.units_std for s in estimate.segments] == pytest.approx(
            list(segments["units_std"])
        )
        assert [s.baseline_units for s in estimate.segments] == pytest.approx(
            list(segments["baseline_units"])
        )


async def test_competitor_price_overrides_reach_the_prediction(
    tools: ToolRegistry, model: DemandModel, skus: list[str]
) -> None:
    result = await tools.call(
        "estimate_demand",
        {
            "options": [option(skus[0])],
            "competitor_prices": [{"region": "North", "sku_id": skus[0], "price": 1.0}],
        },
    )

    assert isinstance(result, ToolOk)
    assert isinstance(result.output, EstimateDemandOutput)
    context = PredictionContext(policy=POLICY, competitor_prices={(Region.NORTH, skus[0]): 1.0})
    expected = model.predict([PlanLine.model_validate(option(skus[0]))], context)
    assert result.output.estimates[0].units == pytest.approx(expected.options["units"].iloc[0])


@pytest.mark.parametrize(
    ("arguments", "loc"),
    [
        ({}, "options"),
        ({"options": []}, "options"),
        ({"options": [option("SKU0001")] * 201}, "options"),
        ({"options": [option("SKU0001", depth_pct=0)]}, "options.0.depth_pct"),
        ({"options": [option("SKU0001", region="Central")]}, "options.0.region"),
        ({"options": [option("SKU0001", mechanism="BOGO", depth_pct=30)]}, "options.0"),
        ({"options": [option("SKU0001")], "policy": {"margin_floor": 0}}, "policy"),
        (
            {
                "options": [option("SKU0001")],
                "competitor_prices": [{"region": "North", "sku_id": "SKU0001", "price": -1}],
            },
            "competitor_prices.0.price",
        ),
    ],
)
async def test_input_that_breaks_the_schema_gives_a_typed_error(
    tools: ToolRegistry, arguments: dict[str, Any], loc: str
) -> None:
    result = await tools.call("estimate_demand", arguments)

    assert isinstance(result, ToolError)
    assert result.code == "invalid_input"
    assert loc in [detail.loc for detail in result.details]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"start_week": AS_OF - 1}, "before the as-of week"),
        ({"sku_id": "SKU9999"}, "unknown SKU SKU9999"),
        ({"region": "East"}, "no stores in East"),
    ],
)
async def test_options_the_model_cannot_predict_give_a_typed_error(
    tools: ToolRegistry, skus: list[str], changes: dict[str, Any], message: str
) -> None:
    result = await tools.call("estimate_demand", {"options": [option(skus[0], **changes)]})

    assert isinstance(result, ToolError)
    assert result.code == "invalid_input"
    assert message in result.message


async def test_no_registered_model_gives_a_typed_error(skus: list[str]) -> None:
    tools = ToolRegistry([estimate_demand_tool(FixedModel(None), policy=POLICY)])

    result = await tools.call("estimate_demand", {"options": [option(skus[0])]})

    assert isinstance(result, ToolError)
    assert result.code == "model_unavailable"


async def test_the_model_is_resolved_on_every_call(
    entry: RegisteredModel, model: DemandModel, skus: list[str]
) -> None:
    source = FixedModel(None)
    tools = ToolRegistry([estimate_demand_tool(source, policy=POLICY)])
    assert isinstance(
        await tools.call("estimate_demand", {"options": [option(skus[0])]}), ToolError
    )

    source.loaded = (entry, model)

    assert isinstance(await tools.call("estimate_demand", {"options": [option(skus[0])]}), ToolOk)
