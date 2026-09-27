"""`simulate_plan` through the tool registry: a plan's ranges and stock-out risk (ADR 0042)."""

from typing import Any

import pytest

from promopilot.agents.tools import ToolError, ToolOk, ToolRegistry
from promopilot.agents.tools.as_of import fixed_as_of_week
from promopilot.agents.tools.simulate_plan import (
    SimulatePlanInput,
    SimulatePlanOutput,
    simulate_plan_tool,
)
from promopilot.datagen import GeneratedDataset
from promopilot.domain import CompanyPolicy, Mechanism, PlanLine, Region, TargetSegment
from promopilot.models.demand import DemandModel
from promopilot.models.registry import ModelKind
from promopilot.models.relations import Relations
from promopilot.simulator import SimulationSettings
from tests.conftest import SMALL_AS_OF
from tests.unit.agents.fakes import InMemoryRetailData
from tests.unit.agents.test_generate_candidates import Fixed, entry

DEFAULTS = SimulationSettings(n_runs=300, seed=4)


def build(
    small_models: tuple[DemandModel, Relations],
    small_dataset: GeneratedDataset,
    *,
    demand: bool = True,
) -> ToolRegistry:
    return ToolRegistry(
        [
            simulate_plan_tool(
                Fixed((entry(ModelKind.DEMAND, 3), small_models[0]) if demand else None),
                InMemoryRetailData(small_dataset),
                fixed_as_of_week(SMALL_AS_OF),
                policy=CompanyPolicy(),
                defaults=DEFAULTS,
            )
        ]
    )


@pytest.fixture
def tools(
    small_models: tuple[DemandModel, Relations], small_dataset: GeneratedDataset
) -> ToolRegistry:
    return build(small_models, small_dataset)


def line(sku_id: str, **changes: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "sku_id": sku_id,
        "region": Region.NORTH.value,
        "mechanism": Mechanism.PCT_OFF.value,
        "depth_pct": 20,
        "duration_weeks": 2,
        "start_week": SMALL_AS_OF + 2,
        "target_segment": TargetSegment.ALL_CUSTOMERS.value,
    }
    return fields | changes


@pytest.fixture
def skus(small_dataset: GeneratedDataset) -> list[str]:
    return sorted(small_dataset.products["sku_id"])


def test_the_registry_lists_simulate_plan_with_its_schemas(tools: ToolRegistry) -> None:
    (spec,) = tools.specs()

    assert spec.name == "simulate_plan"
    assert spec.input_schema == SimulatePlanInput.model_json_schema()
    assert spec.output_schema == SimulatePlanOutput.model_json_schema(mode="serialization")


async def test_a_call_returns_the_plans_simulation_with_the_default_settings(
    tools: ToolRegistry, skus: list[str]
) -> None:
    arguments = {"lines": [line(skus[0]), line(skus[1], region=Region.SOUTH.value)]}

    first = await tools.call("simulate_plan", arguments)
    second = await tools.call("simulate_plan", arguments)

    assert isinstance(first, ToolOk)
    assert isinstance(second, ToolOk)
    output = SimulatePlanOutput.model_validate(first.output.model_dump(mode="json"))
    assert output == second.output
    assert output.as_of_week == SMALL_AS_OF
    assert output.demand_model.version == 3
    simulation = output.simulation
    assert (simulation.n_runs, simulation.seed) == (300, 4)
    assert [(s.sku_id, s.region) for s in simulation.lines] == [
        (skus[0], Region.NORTH),
        (skus[1], Region.SOUTH),
    ]
    assert [r.region for r in simulation.regions] == [Region.NORTH, Region.SOUTH]


async def test_the_planner_may_ask_for_more_runs_within_bounds(
    tools: ToolRegistry, skus: list[str]
) -> None:
    result = await tools.call("simulate_plan", {"lines": [line(skus[0])], "n_runs": 500})

    assert isinstance(result, ToolOk)
    assert isinstance(result.output, SimulatePlanOutput)
    assert result.output.simulation.n_runs == 500


@pytest.mark.parametrize("n_runs", [99, 5_001])
async def test_out_of_range_runs_are_invalid_input(
    tools: ToolRegistry, skus: list[str], n_runs: int
) -> None:
    result = await tools.call("simulate_plan", {"lines": [line(skus[0])], "n_runs": n_runs})

    assert isinstance(result, ToolError)
    assert result.code == "invalid_input"
    assert [detail.loc for detail in result.details] == ["n_runs"]


async def test_a_sku_twice_in_a_region_is_invalid_input(
    tools: ToolRegistry, skus: list[str]
) -> None:
    result = await tools.call(
        "simulate_plan", {"lines": [line(skus[0]), line(skus[0], depth_pct=30)]}
    )

    assert isinstance(result, ToolError)
    assert result.code == "invalid_input"
    assert "one plan line per SKU per region" in result.message


async def test_a_line_before_the_as_of_week_or_an_unknown_sku_is_invalid_input(
    tools: ToolRegistry, skus: list[str]
) -> None:
    early = await tools.call("simulate_plan", {"lines": [line(skus[0], start_week=10)]})
    unknown = await tools.call("simulate_plan", {"lines": [line("SKU9999")]})

    assert isinstance(early, ToolError)
    assert early.code == "invalid_input"
    assert "before the as-of week" in early.message
    assert isinstance(unknown, ToolError)
    assert unknown.code == "invalid_input"


async def test_no_demand_model_is_model_unavailable(
    small_models: tuple[DemandModel, Relations],
    small_dataset: GeneratedDataset,
    skus: list[str],
) -> None:
    tools = build(small_models, small_dataset, demand=False)

    result = await tools.call("simulate_plan", {"lines": [line(skus[0])]})

    assert isinstance(result, ToolError)
    assert result.code == "model_unavailable"


def test_the_input_takes_plan_lines_only_as_plan_lines(skus: list[str]) -> None:
    parsed = SimulatePlanInput.model_validate({"lines": [line(skus[0])]})

    assert isinstance(parsed.lines[0], PlanLine)
    assert parsed.n_runs is None
