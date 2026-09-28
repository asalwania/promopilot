"""The planning stack a session plans with: every SPEC §9.6 tool, the deterministic default
sequence, and the planner agent's tools (ADR 0025, ADR 0038, ADR 0049).

The API (`promopilot.api.planning`), `make record-cassettes` and the eval harness assemble it
here, the same way, so the planner turns one records are the ones the others replay
(ADR 0054, ADR 0056). Only what it plans on differs: the API reads Postgres at the latest week
and the registered models; an eval scenario reads its own in-memory world at a fixed week.
"""

from dataclasses import dataclass, replace
from typing import Any, Protocol, Self

import pandas as pd

from promopilot.agents.planner import OptimisingPlanner, StoredRevisions
from promopilot.agents.planner_agent import AgentTools
from promopilot.agents.tools import ToolRegistry
from promopilot.agents.tools.as_of import AsOfWeekSource
from promopilot.agents.tools.compare_mechanisms import compare_mechanisms_tool
from promopilot.agents.tools.estimate_demand import DemandModelSource, estimate_demand_tool
from promopilot.agents.tools.generate_candidates import generate_candidates_tool
from promopilot.agents.tools.get_competitor_gaps import get_competitor_gaps_tool
from promopilot.agents.tools.get_relations import RelationsSource, get_relations_tool
from promopilot.agents.tools.holidays import get_holidays_tool
from promopilot.agents.tools.inventory_status import get_inventory_status_tool
from promopilot.agents.tools.relax_constraints import relax_constraints_tool
from promopilot.agents.tools.run_optimizer import run_optimizer_tool
from promopilot.agents.tools.scope_data import get_scope_data_tool
from promopilot.agents.tools.simulate_plan import simulate_plan_tool
from promopilot.config import Settings
from promopilot.domain import CompanyPolicy
from promopilot.guardrails import RiskThresholds
from promopilot.optimizer import CandidateStore, SolverSettings
from promopilot.simulator import SimulationSettings

RECORDED_SETTINGS = {
    "optimizer_deterministic_limit",
    "optimizer_binding_deterministic_limit",
    "optimizer_relaxation_deterministic_limit",
    "optimizer_time_limit_seconds",
    "optimizer_workers",
    "optimizer_seed",
    "optimizer_binding_time_limit_seconds",
    "optimizer_relaxation_time_limit_seconds",
    "simulation_runs",
    "simulation_seed",
    "critic_line_spend_share",
    "critic_group_spend_share",
    "critic_cannibalisation_share",
    "critic_stockout_probability",
}
"""What a plan, and so every Critic and Explainer request, depends on besides the data and the
models (ADR 0054): the optimiser's work budgets decide it (ADR 0055), and its wall-clock nets
only when one is hit."""


@dataclass(frozen=True)
class PlanningSettings:
    """How a session plans, from the environment: the optimiser's budgets and seed, the
    simulation's runs and seed, and the Critic's thresholds (ADR 0051, ADR 0055)."""

    solver: SolverSettings
    """The optimiser's work budgets, wall-clock nets and workers (ADR 0055)."""
    seed: int
    """The optimiser's seed (`OPTIMIZER_SEED`)."""
    simulation: SimulationSettings
    risk_thresholds: RiskThresholds
    """When the Critic's risk review flags a plan (`CRITIC_*`, ADR 0051)."""
    recorded: dict[str, Any]
    """The settings that shape what the LLM is shown: a recording notes them, and a stack
    that plans with others cannot replay it (ADR 0054)."""

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        return cls(
            solver=SolverSettings(
                time_limit_seconds=settings.optimizer_time_limit_seconds,
                workers=settings.optimizer_workers,
                binding_time_limit_seconds=settings.optimizer_binding_time_limit_seconds,
                relaxation_time_limit_seconds=settings.optimizer_relaxation_time_limit_seconds,
                deterministic_limit=settings.optimizer_deterministic_limit,
                binding_deterministic_limit=settings.optimizer_binding_deterministic_limit,
                relaxation_deterministic_limit=settings.optimizer_relaxation_deterministic_limit,
            ),
            seed=settings.optimizer_seed,
            simulation=SimulationSettings(
                n_runs=settings.simulation_runs, seed=settings.simulation_seed
            ),
            risk_thresholds=RiskThresholds(
                line_spend_share=settings.critic_line_spend_share,
                group_spend_share=settings.critic_group_spend_share,
                cannibalisation_share=settings.critic_cannibalisation_share,
                stockout_probability=settings.critic_stockout_probability,
            ),
            recorded=settings.model_dump(include=RECORDED_SETTINGS),
        )

    def seeded(self, seed: int) -> Self:
        """The same settings with `seed` as both the optimiser's and the simulation's seed: an
        eval scenario's (ADR 0056)."""
        return replace(
            self,
            seed=seed,
            simulation=replace(self.simulation, seed=seed),
            recorded={**self.recorded, "optimizer_seed": seed, "simulation_seed": seed},
        )


class PlanningData(Protocol):
    """Every read the tools and the default sequence make (`promopilot.data.RetailData`, or
    `promopilot.data.InMemoryRetailData`)."""

    async def products(self) -> pd.DataFrame: ...
    async def stores(self) -> pd.DataFrame: ...
    async def calendar(self) -> pd.DataFrame: ...
    async def inventory(self, as_of_week: int) -> pd.DataFrame: ...
    async def latest_competitor_prices(self, as_of_week: int) -> pd.DataFrame: ...


@dataclass(frozen=True)
class PlanningStack:
    planner: OptimisingPlanner
    """The deterministic default sequence (ADR 0038), and the planner agent's fallback."""
    candidates: CandidateStore
    """Generated promo options, waiting for the optimiser (ADR 0035, ADR 0036)."""
    tools: ToolRegistry
    """Every SPEC §9.6 tool, which the planner agent is offered (ADR 0049)."""

    @property
    def agent(self) -> AgentTools:
        """The planner agent's tools: the registry, and the plan revision of a candidate set
        its `run_optimizer` solved."""
        return AgentTools(
            tools=self.tools, revisions=StoredRevisions(self.candidates, self.planner)
        )


def planning_stack(
    demand_model: DemandModelSource,
    relations_model: RelationsSource,
    data: PlanningData,
    *,
    policy: CompanyPolicy,
    solver: SolverSettings,
    simulation: SimulationSettings,
    seed: int,
    as_of_week: AsOfWeekSource,
) -> PlanningStack:
    """The tools and the default sequence, planning on `data` with the models the sources give
    on each call, the optimiser's `seed` and the simulation's settings. The data tools read at
    `as_of_week` (ADR 0032)."""
    candidates = CandidateStore()
    tools = ToolRegistry(
        [
            estimate_demand_tool(demand_model, policy=policy),
            get_scope_data_tool(data),
            get_inventory_status_tool(data, as_of_week, policy=policy),
            get_holidays_tool(data, as_of_week),
            get_competitor_gaps_tool(data, as_of_week, policy=policy),
            get_relations_tool(relations_model, data),
            generate_candidates_tool(
                demand_model, relations_model, data, as_of_week, policy=policy, store=candidates
            ),
            run_optimizer_tool(candidates, policy=policy, settings=solver, seed=seed),
            relax_constraints_tool(candidates, policy=policy, settings=solver, seed=seed),
            compare_mechanisms_tool(demand_model, relations_model, data, as_of_week, policy=policy),
            simulate_plan_tool(demand_model, data, as_of_week, policy=policy, defaults=simulation),
        ]
    )
    planner = OptimisingPlanner(
        demand_model,
        relations_model,
        data,
        policy=policy,
        settings=solver,
        seed=seed,
        simulation=simulation,
    )
    return PlanningStack(planner=planner, candidates=candidates, tools=tools)
