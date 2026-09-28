"""The planning stack a session plans with: the models, the data, the default sequence, the
planner agent's tool registry and the Critic's risk thresholds (ADR 0025, ADR 0038, ADR 0049,
ADR 0051).

The API and `make record-cassettes` build it the same way, so the recorded planner turns are
the ones a session replays.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from promopilot.agents import AgentTools, OptimisingPlanner, RecordedPlanning, StoredRevisions
from promopilot.agents.tools import ToolRegistry
from promopilot.agents.tools.compare_mechanisms import compare_mechanisms_tool
from promopilot.agents.tools.estimate_demand import estimate_demand_tool
from promopilot.agents.tools.generate_candidates import generate_candidates_tool
from promopilot.agents.tools.get_competitor_gaps import get_competitor_gaps_tool
from promopilot.agents.tools.get_relations import get_relations_tool
from promopilot.agents.tools.holidays import get_holidays_tool
from promopilot.agents.tools.inventory_status import get_inventory_status_tool
from promopilot.agents.tools.relax_constraints import relax_constraints_tool
from promopilot.agents.tools.run_optimizer import run_optimizer_tool
from promopilot.agents.tools.scope_data import get_scope_data_tool
from promopilot.agents.tools.simulate_plan import simulate_plan_tool
from promopilot.config import Settings
from promopilot.data import RetailData
from promopilot.domain import CompanyPolicy
from promopilot.guardrails import RiskThresholds
from promopilot.models.demand import DemandModel
from promopilot.models.registry import LatestModel, ModelKind, ModelRegistry
from promopilot.models.relations import Relations
from promopilot.models.serving import LiveRelations
from promopilot.optimizer import CandidateStore, SolverSettings
from promopilot.simulator import SimulationSettings


@dataclass(frozen=True)
class Planning:
    registry: ModelRegistry
    demand_model: LatestModel[DemandModel]
    relations_model: LiveRelations[Relations]
    data: RetailData
    policy: CompanyPolicy
    simulation: SimulationSettings
    solver: SolverSettings
    """The optimiser's work budgets, wall-clock nets and workers (ADR 0055)."""
    planner: OptimisingPlanner
    """The deterministic default sequence (ADR 0038), and the planner agent's fallback."""
    candidates: CandidateStore
    tools: ToolRegistry
    """Every SPEC §9.6 tool, which the planner agent is offered (ADR 0049)."""
    risk_thresholds: RiskThresholds
    """When the Critic's risk review flags a plan (`CRITIC_*`, ADR 0051)."""
    recorded_settings: dict[str, Any]
    """The settings that shape what the LLM is shown: a recording notes them, and a stack
    that plans with others cannot replay it (ADR 0054)."""

    @property
    def agent(self) -> AgentTools:
        """The planner agent's tools: the registry, and the plan revision of a candidate set
        its `run_optimizer` solved."""
        return AgentTools(
            tools=self.tools, revisions=StoredRevisions(self.candidates, self.planner)
        )

    def recorded(self) -> RecordedPlanning:
        """What `make record-cassettes` and its check play the session scripts with."""
        return RecordedPlanning(
            agent=self.agent,
            default=self.planner,
            policy=self.policy,
            risk_thresholds=self.risk_thresholds,
            settings=self.recorded_settings,
        )


def build_planning(settings: Settings, engine: AsyncEngine) -> Planning:
    registry = ModelRegistry(engine, settings.model_dir)
    demand_model = LatestModel(registry, ModelKind.DEMAND, DemandModel)
    # Relations are served only on the demand model they were fitted on (ADR 0033).
    relations_model = LiveRelations(
        LatestModel(registry, ModelKind.RELATIONS, Relations), demand_model
    )
    data = RetailData(engine)
    policy = CompanyPolicy()
    solver = SolverSettings(
        time_limit_seconds=settings.optimizer_time_limit_seconds,
        workers=settings.optimizer_workers,
        binding_time_limit_seconds=settings.optimizer_binding_time_limit_seconds,
        relaxation_time_limit_seconds=settings.optimizer_relaxation_time_limit_seconds,
        deterministic_limit=settings.optimizer_deterministic_limit,
        binding_deterministic_limit=settings.optimizer_binding_deterministic_limit,
        relaxation_deterministic_limit=settings.optimizer_relaxation_deterministic_limit,
    )
    simulation = SimulationSettings(n_runs=settings.simulation_runs, seed=settings.simulation_seed)
    seed = settings.optimizer_seed
    # The models are resolved per call, so a retrain is picked up, and so is the as-of week,
    # so newly loaded data moves the data tools' clock (ADR 0025, ADR 0032). Generated promo
    # options wait in the candidate store for the optimiser (ADR 0035, ADR 0036); the
    # simulator samples with the session's seed and default runs (ADR 0042).
    candidates = CandidateStore()
    week = data.default_as_of_week
    tools = ToolRegistry(
        [
            estimate_demand_tool(demand_model, policy=policy),
            get_scope_data_tool(data),
            get_inventory_status_tool(data, week, policy=policy),
            get_holidays_tool(data, week),
            get_competitor_gaps_tool(data, week, policy=policy),
            get_relations_tool(relations_model, data),
            generate_candidates_tool(
                demand_model, relations_model, data, week, policy=policy, store=candidates
            ),
            run_optimizer_tool(candidates, policy=policy, settings=solver, seed=seed),
            relax_constraints_tool(candidates, policy=policy, settings=solver, seed=seed),
            compare_mechanisms_tool(demand_model, relations_model, data, week, policy=policy),
            simulate_plan_tool(demand_model, data, week, policy=policy, defaults=simulation),
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
    return Planning(
        registry=registry,
        demand_model=demand_model,
        relations_model=relations_model,
        data=data,
        policy=policy,
        simulation=simulation,
        solver=solver,
        planner=planner,
        candidates=candidates,
        tools=tools,
        risk_thresholds=RiskThresholds(
            line_spend_share=settings.critic_line_spend_share,
            group_spend_share=settings.critic_group_spend_share,
            cannibalisation_share=settings.critic_cannibalisation_share,
            stockout_probability=settings.critic_stockout_probability,
        ),
        recorded_settings=settings.model_dump(include=RECORDED_SETTINGS),
    )


RECORDED_SETTINGS = {
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
models (ADR 0054)."""
