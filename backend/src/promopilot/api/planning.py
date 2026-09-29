"""The planning stack a session plans with: the models, the data, the default sequence, the
planner agent's tool registry and the Critic's risk thresholds (ADR 0025, ADR 0038, ADR 0049,
ADR 0051).

The tools and the default sequence are assembled by `promopilot.agents.planning_stack`, as
`make record-cassettes` and the eval harness assemble them, so the recorded planner turns are
the ones a session replays (ADR 0054, ADR 0056). Here they plan on Postgres at the latest week
with the registered models.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from promopilot.agents import (
    AgentTools,
    OptimisingPlanner,
    PlanningSettings,
    RecordedPlanning,
    StoredRevisions,
    planning_stack,
)
from promopilot.agents.tools import ToolRegistry
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
    planning = PlanningSettings.from_settings(settings)
    # The models are resolved per call, so a retrain is picked up, and so is the as-of week,
    # so newly loaded data moves the data tools' clock (ADR 0025, ADR 0032). Generated promo
    # options wait in the candidate store for the optimiser (ADR 0035, ADR 0036); the
    # simulator samples with the session's seed and default runs (ADR 0042). A tool call that
    # outlives TOOL_TIMEOUT_SECONDS is a `timeout` tool error (ADR 0071).
    stack = planning_stack(
        demand_model,
        relations_model,
        data,
        policy=policy,
        solver=planning.solver,
        simulation=planning.simulation,
        seed=planning.seed,
        as_of_week=data.default_as_of_week,
        tool_timeout_s=settings.tool_timeout_seconds,
    )
    return Planning(
        registry=registry,
        demand_model=demand_model,
        relations_model=relations_model,
        data=data,
        policy=policy,
        simulation=planning.simulation,
        solver=planning.solver,
        planner=stack.planner,
        candidates=stack.candidates,
        tools=stack.tools,
        risk_thresholds=planning.risk_thresholds,
        recorded_settings=planning.recorded,
    )
