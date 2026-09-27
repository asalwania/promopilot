"""Re-simulate a stored plan revision over HTTP (SPEC §10, F-09, ADR 0042, ADR 0043).

`POST /api/plans/{id}/simulate`: `{id}` is the planning session's id and the plan is its latest
plan revision, the one `GET /api/sessions/{id}` shows. The revision is simulated on the latest
demand model with the configured seed, units capped at the stock of the planning request's
as-of week, and the result replaces the revision's stored simulation. The revision number and
its plan lines stay as they are. An optional competitor reaction stress-tests the plan against a
price war, and the stored simulation records it (ADR 0045).
"""

from typing import Protocol
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from promopilot.agents.tools import ToolCallError
from promopilot.agents.tools.estimate_demand import DemandModelSource
from promopilot.agents.tools.simulate_plan import SimulationData, simulate_on_latest_model
from promopilot.api.schemas import PlanSimulationResponse, SimulatePlanRequest
from promopilot.domain import (
    CompanyPolicy,
    CompetitorReaction,
    PlanningSession,
    PlanSimulation,
    PromoPlan,
    SessionStatus,
)
from promopilot.simulator import SimulationSettings

UNAVAILABLE = {"model_unavailable", "data_unavailable"}


class ApprovedPlanError(Exception):
    """An approved plan revision is final: its stored simulation is part of what was approved
    (ADR 0046)."""


class PlanRevisions(Protocol):
    """The session reads and simulation writes it makes (`promopilot.data.SessionStore`)."""

    async def get(self, session_id: UUID) -> PlanningSession | None: ...
    async def save_simulation(
        self, session_id: UUID, revision_number: int, simulation: PlanSimulation
    ) -> None: ...


class PlanService:
    def __init__(
        self,
        *,
        revisions: PlanRevisions,
        demand_models: DemandModelSource,
        data: SimulationData,
        policy: CompanyPolicy,
        defaults: SimulationSettings,
    ) -> None:
        self._revisions = revisions
        self._demand_models = demand_models
        self._data = data
        self._policy = policy
        self._defaults = defaults

    async def simulate(
        self,
        session_id: UUID,
        n_runs: int | None,
        competitor_reaction: CompetitorReaction | None = None,
    ) -> PlanSimulationResponse | None:
        """None when the session is unknown or has no plan revision yet. Raises
        `ToolCallError` when the revision cannot be simulated now (`simulate_on_latest_model`),
        and `ApprovedPlanError` when the session is approved."""
        session = await self._revisions.get(session_id)
        if session is None or session.latest_revision is None or session.planning_request is None:
            return None
        if session.status is SessionStatus.APPROVED:
            raise ApprovedPlanError(
                f"plan revision {session.latest_revision.number} is approved and final"
            )
        revision = session.latest_revision
        week = session.planning_request.as_of_week
        simulated = await simulate_on_latest_model(
            PromoPlan(lines=tuple(planned.line for planned in revision.lines)),
            self._demand_models,
            self._data,
            week,
            policy=self._policy,
            n_runs=n_runs or self._defaults.n_runs,
            seed=self._defaults.seed,
            competitor_reaction=competitor_reaction,
        )
        await self._revisions.save_simulation(session_id, revision.number, simulated.simulation)
        return PlanSimulationResponse(
            session_id=session_id,
            revision_number=revision.number,
            demand_model=simulated.demand_model,
            as_of_week=week,
            simulation=simulated.simulation,
        )


def plans_router(plans: PlanService) -> APIRouter:
    router = APIRouter(prefix="/api/plans", tags=["plans"])

    @router.post(
        "/{session_id}/simulate",
        responses={
            status.HTTP_404_NOT_FOUND: {
                "description": "Unknown session, or a session without a plan revision yet"
            },
            status.HTTP_409_CONFLICT: {
                "description": "The session is approved, so its plan is final, or the latest "
                "demand model cannot simulate the stored plan"
            },
            status.HTTP_503_SERVICE_UNAVAILABLE: {
                "description": "No trained demand model, or no inventory snapshot for the "
                "planning request's as-of week"
            },
        },
    )
    async def simulate_plan(session_id: UUID, body: SimulatePlanRequest) -> PlanSimulationResponse:
        """Re-simulate the session's latest plan revision and store the result against it."""
        try:
            found = await plans.simulate(session_id, body.n_runs, body.competitor_reaction)
        except ToolCallError as failure:
            code = (
                status.HTTP_503_SERVICE_UNAVAILABLE
                if failure.error.code in UNAVAILABLE
                else status.HTTP_409_CONFLICT
            )
            raise HTTPException(code, failure.error.message) from failure
        except ApprovedPlanError as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
        if found is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown plan")
        return found

    return router
