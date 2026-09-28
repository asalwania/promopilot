"""The planning stack: the tools, the default sequence and the planner agent's tools, assembled
the same way for the API, `make record-cassettes` and the eval harness (ADR 0056)."""

from promopilot.agents import PlanningSettings, planning_stack
from promopilot.agents.tools import ToolOk
from promopilot.agents.tools.as_of import fixed_as_of_week
from promopilot.config import Settings
from promopilot.datagen import GeneratedDataset
from promopilot.domain import CompanyPolicy
from promopilot.models.demand import DemandModel
from promopilot.models.registry import ModelKind
from promopilot.models.relations import Relations
from promopilot.optimizer import SolverSettings
from promopilot.simulator import SimulationSettings
from tests.unit.agents.fakes import InMemoryRetailData
from tests.unit.agents.test_generate_candidates import Fixed, entry

SPEC_TOOLS = [
    "estimate_demand",
    "get_scope_data",
    "get_inventory_status",
    "get_holidays",
    "get_competitor_gaps",
    "get_relations",
    "generate_candidates",
    "run_optimizer",
    "relax_constraints",
    "compare_mechanisms",
    "simulate_plan",
]
"""SPEC §9.6's tools, in the order the planner agent is offered them: a recorded tool request's
hash covers the order."""


async def test_the_stack_offers_every_spec_tool_in_order(
    small_dataset: GeneratedDataset, small_models: tuple[DemandModel, Relations]
) -> None:
    stack = planning_stack(
        Fixed((entry(ModelKind.DEMAND, 1), small_models[0])),
        Fixed((entry(ModelKind.RELATIONS, 1), small_models[1])),
        InMemoryRetailData(small_dataset),
        policy=CompanyPolicy(),
        solver=SolverSettings(),
        simulation=SimulationSettings(n_runs=200, seed=3),
        seed=3,
        as_of_week=fixed_as_of_week(52),
    )

    assert [spec.name for spec in stack.tools.specs()] == SPEC_TOOLS
    assert stack.agent.tools is stack.tools


async def test_the_data_tools_read_at_the_bound_as_of_week(
    small_dataset: GeneratedDataset, small_models: tuple[DemandModel, Relations]
) -> None:
    data = InMemoryRetailData(small_dataset)
    stack = planning_stack(
        Fixed((entry(ModelKind.DEMAND, 1), small_models[0])),
        Fixed((entry(ModelKind.RELATIONS, 1), small_models[1])),
        data,
        policy=CompanyPolicy(),
        solver=SolverSettings(),
        simulation=SimulationSettings(n_runs=200, seed=3),
        seed=3,
        as_of_week=fixed_as_of_week(40),
    )

    result = await stack.tools.call("get_inventory_status", {"overstocked_only": False})

    assert isinstance(result, ToolOk)
    assert data.inventory_as_of_weeks == [40]


def test_a_seed_sets_the_optimisers_and_the_simulations_and_is_recorded() -> None:
    settings = PlanningSettings.from_settings(Settings())

    seeded = settings.seeded(7)

    assert (seeded.seed, seeded.simulation.seed) == (7, 7)
    assert seeded.simulation.n_runs == settings.simulation.n_runs
    assert seeded.solver == settings.solver
    assert seeded.recorded == {**settings.recorded, "optimizer_seed": 7, "simulation_seed": 7}
