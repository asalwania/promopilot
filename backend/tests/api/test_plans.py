"""`POST /api/plans/{id}/simulate`: re-simulate a session's latest plan revision (ADR 0043),
optionally with a competitor reaction (ADR 0045)."""

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from promopilot.api.main import create_app
from promopilot.api.plans import PlanService
from promopilot.datagen import GeneratedDataset
from promopilot.domain import (
    CompanyPolicy,
    CompetitorReaction,
    Mechanism,
    PlanLine,
    PlanningRequest,
    PlanningSession,
    PlanRevision,
    PlanRevisionLine,
    PlanSimulation,
    PromoWindow,
    Region,
    Scope,
    SessionStatus,
    TargetSegment,
)
from promopilot.models.demand import DemandModel
from promopilot.models.registry import ModelKind
from promopilot.models.relations import Relations
from promopilot.simulator import SimulationSettings
from tests.conftest import SMALL_AS_OF
from tests.offline import NoModel, offline_sessions
from tests.unit.agents.fakes import InMemoryRetailData
from tests.unit.agents.test_generate_candidates import Fixed, entry

DEFAULTS = SimulationSettings(n_runs=300, seed=4)
REQUEST = PlanningRequest(
    as_of_week=SMALL_AS_OF,
    scope=Scope(regions=(Region.NORTH,), categories=("Snacks",)),
    promo_window=PromoWindow(start_week=SMALL_AS_OF + 2, end_week=SMALL_AS_OF + 3),
    marketing_budget=20_000.0,
)


class InMemoryRevisions:
    """The session store's reads and simulation writes, in memory."""

    def __init__(self, *sessions: PlanningSession) -> None:
        self.sessions = {session.id: session for session in sessions}

    async def get(self, session_id: UUID) -> PlanningSession | None:
        return self.sessions.get(session_id)

    async def save_simulation(
        self, session_id: UUID, revision_number: int, simulation: PlanSimulation
    ) -> None:
        session = self.sessions[session_id]
        assert session.latest_revision is not None
        assert session.latest_revision.number == revision_number
        revision = session.latest_revision.model_copy(update={"simulation": simulation})
        self.sessions[session_id] = session.model_copy(update={"latest_revision": revision})


class HealthyProbe:
    async def is_healthy(self) -> bool:
        return True


def planned(sku_id: str, region: Region) -> PlanRevisionLine:
    return PlanRevisionLine(
        line=PlanLine(
            sku_id=sku_id,
            region=region,
            mechanism=Mechanism.PCT_OFF,
            depth_pct=20,
            duration_weeks=2,
            start_week=SMALL_AS_OF + 2,
            target_segment=TargetSegment.ALL_CUSTOMERS,
        ),
        expected_units=100.0,
        promo_cost=500.0,
        expected_incremental_profit=50.0,
    )


def session_with(
    revision: PlanRevision | None, request: PlanningRequest = REQUEST
) -> PlanningSession:
    return PlanningSession(
        id=uuid4(),
        brief="Snacks push in the North",
        status=SessionStatus.PLANNING if revision is None else SessionStatus.AWAITING_APPROVAL,
        planning_request=None if revision is None else request,
        latest_revision=revision,
    )


@pytest.fixture
def revision(small_dataset: GeneratedDataset) -> PlanRevision:
    skus = sorted(small_dataset.products["sku_id"])
    return PlanRevision(
        number=1, lines=(planned(skus[0], Region.NORTH), planned(skus[1], Region.SOUTH))
    )


def client_for(
    revisions: InMemoryRevisions,
    small_models: tuple[DemandModel, Relations],
    small_dataset: GeneratedDataset,
    *,
    demand: bool = True,
) -> AsyncClient:
    plans = PlanService(
        revisions=revisions,
        demand_models=Fixed((entry(ModelKind.DEMAND, 3), small_models[0]) if demand else None),
        data=InMemoryRetailData(small_dataset),
        policy=CompanyPolicy(),
        defaults=DEFAULTS,
    )
    app = create_app(
        database_probe=HealthyProbe(),
        model_status=NoModel(),
        sessions=offline_sessions(),
        plans=plans,
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def simulate(client: AsyncClient, session_id: UUID, body: dict[str, Any]) -> Any:
    return await client.post(f"/api/plans/{session_id}/simulate", json=body)


async def test_a_resimulation_returns_the_result_and_replaces_the_stored_one(
    small_models: tuple[DemandModel, Relations],
    small_dataset: GeneratedDataset,
    revision: PlanRevision,
) -> None:
    session = session_with(revision)
    revisions = InMemoryRevisions(session)
    async with client_for(revisions, small_models, small_dataset) as client:
        response = await simulate(client, session.id, {"n_runs": 500})

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == str(session.id)
    assert body["revision_number"] == 1
    assert body["as_of_week"] == SMALL_AS_OF
    assert body["demand_model"]["version"] == 3
    simulation = PlanSimulation.model_validate(body["simulation"])
    # The seed is configuration (ADR 0042); the caller chooses only the runs.
    assert (simulation.n_runs, simulation.seed) == (500, DEFAULTS.seed)
    assert [(s.sku_id, s.region) for s in simulation.lines] == [
        (planned.line.sku_id, planned.line.region) for planned in revision.lines
    ]
    stored = revisions.sessions[session.id].latest_revision
    assert stored is not None
    assert stored.simulation == simulation
    assert stored.number == 1
    assert stored.lines == revision.lines


async def test_the_same_request_gives_the_same_result(
    small_models: tuple[DemandModel, Relations],
    small_dataset: GeneratedDataset,
    revision: PlanRevision,
) -> None:
    session = session_with(revision)
    async with client_for(InMemoryRevisions(session), small_models, small_dataset) as client:
        first = await simulate(client, session.id, {"n_runs": 200})
        second = await simulate(client, session.id, {"n_runs": 200})

    assert first.json() == second.json()


@pytest.mark.parametrize("body", [{}, {"competitor_reaction": None}], ids=["empty", "null"])
async def test_runs_default_to_the_configured_number(
    small_models: tuple[DemandModel, Relations],
    small_dataset: GeneratedDataset,
    revision: PlanRevision,
    body: dict[str, Any],
) -> None:
    session = session_with(revision)
    async with client_for(InMemoryRevisions(session), small_models, small_dataset) as client:
        response = await simulate(client, session.id, body)

    assert response.status_code == 200
    assert response.json()["simulation"]["n_runs"] == DEFAULTS.n_runs


async def test_an_unknown_plan_is_404(
    small_models: tuple[DemandModel, Relations], small_dataset: GeneratedDataset
) -> None:
    async with client_for(InMemoryRevisions(), small_models, small_dataset) as client:
        response = await simulate(client, uuid4(), {"n_runs": 200})

    assert response.status_code == 404


async def test_a_session_without_a_plan_revision_is_404(
    small_models: tuple[DemandModel, Relations], small_dataset: GeneratedDataset
) -> None:
    session = session_with(None)
    async with client_for(InMemoryRevisions(session), small_models, small_dataset) as client:
        response = await simulate(client, session.id, {"n_runs": 200})

    assert response.status_code == 404


async def test_a_competitor_reaction_is_simulated_and_stored_with_the_result(
    small_models: tuple[DemandModel, Relations],
    small_dataset: GeneratedDataset,
    revision: PlanRevision,
) -> None:
    session = session_with(revision)
    revisions = InMemoryRevisions(session)
    async with client_for(revisions, small_models, small_dataset) as client:
        calm = await simulate(client, session.id, {"n_runs": 200})
        never = await simulate(
            client,
            session.id,
            {"n_runs": 200, "competitor_reaction": {"match_probability": 0.0}},
        )
        war = await simulate(
            client,
            session.id,
            {"n_runs": 200, "competitor_reaction": {"match_probability": 1.0}},
        )

    assert war.status_code == 200
    assert calm.json()["simulation"]["competitor_reaction"] is None
    assert never.json()["simulation"]["competitor_reaction"] == {"match_probability": 0.0}
    assert never.json()["simulation"]["lines"] == calm.json()["simulation"]["lines"]
    simulation = PlanSimulation.model_validate(war.json()["simulation"])
    assert simulation.competitor_reaction == CompetitorReaction(match_probability=1.0)
    stored = revisions.sessions[session.id].latest_revision
    assert stored is not None
    assert stored.simulation == simulation


@pytest.mark.parametrize(
    "body",
    [
        {"n_runs": 99},
        {"n_runs": 5_001},
        {"competitor_reaction": {"match_probability": 1.5}},
        {"competitor_reaction": {"match_probability": -0.1}},
        {"competitor_reaction": {}},
        {"competitor_reaction": {"match_probability": 0.5, "match_share": 0.5}},
        {"competitor_reaction": 0.5},
    ],
    ids=[
        "too-few-runs",
        "too-many-runs",
        "probability-above-one",
        "probability-below-zero",
        "no-probability",
        "unknown-reaction-field",
        "bare-probability",
    ],
)
async def test_out_of_range_runs_and_an_invalid_competitor_reaction_are_422(
    small_models: tuple[DemandModel, Relations],
    small_dataset: GeneratedDataset,
    revision: PlanRevision,
    body: dict[str, Any],
) -> None:
    session = session_with(revision)
    revisions = InMemoryRevisions(session)
    async with client_for(revisions, small_models, small_dataset) as client:
        response = await simulate(client, session.id, body)

    assert response.status_code == 422
    assert revisions.sessions[session.id] == session


async def test_no_trained_demand_model_is_503(
    small_models: tuple[DemandModel, Relations],
    small_dataset: GeneratedDataset,
    revision: PlanRevision,
) -> None:
    session = session_with(revision)
    async with client_for(
        InMemoryRevisions(session), small_models, small_dataset, demand=False
    ) as client:
        response = await simulate(client, session.id, {"n_runs": 200})

    assert response.status_code == 503


async def test_no_inventory_snapshot_for_the_as_of_week_is_503(
    small_models: tuple[DemandModel, Relations],
    small_dataset: GeneratedDataset,
    revision: PlanRevision,
) -> None:
    future = PlanningRequest(
        as_of_week=500,
        scope=REQUEST.scope,
        promo_window=PromoWindow(start_week=502, end_week=503),
        marketing_budget=REQUEST.marketing_budget,
    )
    session = session_with(revision, future)
    async with client_for(InMemoryRevisions(session), small_models, small_dataset) as client:
        response = await simulate(client, session.id, {"n_runs": 200})

    assert response.status_code == 503


class HangingDemand:
    """A demand model source that never answers, like a stalled model load."""

    async def get(self) -> Any:
        await asyncio.Event().wait()


async def test_a_simulation_that_takes_too_long_is_504_and_stores_nothing(
    small_dataset: GeneratedDataset, revision: PlanRevision
) -> None:
    session = session_with(revision)
    revisions = InMemoryRevisions(session)
    plans = PlanService(
        revisions=revisions,
        demand_models=HangingDemand(),
        data=InMemoryRetailData(small_dataset),
        policy=CompanyPolicy(),
        defaults=DEFAULTS,
        timeout_s=0.01,
    )
    app = create_app(
        database_probe=HealthyProbe(),
        model_status=NoModel(),
        sessions=offline_sessions(),
        plans=plans,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await simulate(client, session.id, {"n_runs": 200})

    assert response.status_code == 504
    body = response.json()
    assert body["code"] == "timeout"
    assert body["detail"] == "The simulation took longer than 0.01 s and was stopped."
    assert revisions.sessions[session.id] == session
