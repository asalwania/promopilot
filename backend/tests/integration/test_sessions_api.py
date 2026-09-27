"""The session API over HTTP, with a FakeProvider and the optimising planner on the small
world's fitted models, against real Postgres (E3 seam 1, E6 seam 5)."""

import asyncio
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.community.postgres import PostgresContainer

from promopilot.agents import BriefReading, OptimisingPlanner
from promopilot.agents.session import Planner
from promopilot.agents.tools.inventory_status import pooled_stock
from promopilot.api.main import create_app
from promopilot.api.plans import PlanService
from promopilot.api.sessions import SessionService
from promopilot.data import RetailData, SessionStore, load_dataset
from promopilot.datagen import GeneratedDataset, write
from promopilot.domain import (
    ClearanceShortfall,
    ClearanceTarget,
    CompanyPolicy,
    ConstraintKind,
    Mechanism,
    PlanningRequest,
    PlanRevision,
    PromoWindow,
    Region,
    Relaxation,
    RelaxedConstraint,
    Scope,
    SolveStatus,
)
from promopilot.llm import FakeProvider, LLMError, LLMProvider, Message, ToolSpec, ToolTurn
from promopilot.models.demand import DemandModel
from promopilot.models.registry import ModelKind
from promopilot.models.relations import Relations
from promopilot.optimizer import SolverSettings
from promopilot.simulator import SimulationSettings
from tests.offline import NoModel
from tests.unit.agents.test_generate_candidates import Fixed, entry

pytestmark = pytest.mark.integration

HISTORY_WEEKS = 52  # small_config
BUDGET = 20_000.0
READING = BriefReading(
    regions=[Region.NORTH],
    categories=["Snacks"],
    sku_ids=None,
    promo_start_week=HISTORY_WEEKS + 2,
    promo_end_week=HISTORY_WEEKS + 3,
    marketing_budget=BUDGET,
    min_margin=None,
)
BRIEF = "Snacks push in the North over the next festival, ₹20k budget"
FREE = CompanyPolicy(margin_floor=0.10, fixed_cost_per_line_week=dict.fromkeys(Mechanism, 0.0))
"""Without fixed marketing costs, some of the small world's options pay for themselves."""


class HealthyProbe:
    async def is_healthy(self) -> bool:
        return True


class GatedProvider:
    """Holds every call until the test opens the gate, so `planning` is observable."""

    def __init__(self, inner: LLMProvider) -> None:
        self.inner = inner
        self.gate = asyncio.Event()

    async def complete_structured[T: BaseModel](
        self, schema: type[T], messages: Sequence[Message]
    ) -> T:
        await self.gate.wait()
        return await self.inner.complete_structured(schema, messages)

    async def complete_with_tools(
        self, tools: Sequence[ToolSpec], messages: Sequence[Message]
    ) -> ToolTurn:
        await self.gate.wait()
        return await self.inner.complete_with_tools(tools, messages)


@pytest.fixture(scope="module")
def postgres_url(
    small_dataset: GeneratedDataset, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[str]:
    data_dir: Path = tmp_path_factory.mktemp("data")
    write(small_dataset, data_dir)
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as postgres:
        url = postgres.get_connection_url()
        asyncio.run(load_dataset(data_dir, url))
        yield url


type Api = Callable[..., AbstractAsyncContextManager[AsyncClient]]


@pytest.fixture
def running_api(small_models: tuple[DemandModel, Relations]) -> Api:
    """Starts one API process planning on the small world's fitted models; `planning`
    wraps its planner."""

    def start(
        url: str, llm: LLMProvider, planning: Callable[[Planner], Planner] | None = None
    ) -> AbstractAsyncContextManager[AsyncClient]:
        return api_process(url, llm, small_models, planning)

    return start


@asynccontextmanager
async def api_process(
    url: str,
    llm: LLMProvider,
    models: tuple[DemandModel, Relations] | None,
    planning: Callable[[Planner], Planner] | None = None,
) -> AsyncIterator[AsyncClient]:
    """One API process: its own engine, startup and shutdown, like a uvicorn worker."""
    engine = create_async_engine(url)
    data = RetailData(engine)
    demand = Fixed(None if models is None else (entry(ModelKind.DEMAND, 1), models[0]))
    simulation = SimulationSettings(n_runs=200, seed=0)
    planner = OptimisingPlanner(
        demand,
        Fixed(None if models is None else (entry(ModelKind.RELATIONS, 1), models[1])),
        data,
        policy=FREE,
        settings=SolverSettings(),
        seed=0,
        simulation=simulation,
    )
    store = SessionStore(engine)
    sessions = SessionService(
        store=store, data=data, llm=llm, planner=planning(planner) if planning else planner
    )
    plans = PlanService(
        revisions=store, demand_models=demand, data=data, policy=FREE, defaults=simulation
    )
    app: FastAPI = create_app(
        database_probe=HealthyProbe(), model_status=NoModel(), sessions=sessions, plans=plans
    )
    try:
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                yield client
    finally:
        await engine.dispose()


async def settled(client: AsyncClient, session_id: str) -> dict[str, Any]:
    for _ in range(600):
        body: dict[str, Any] = (await client.get(f"/api/sessions/{session_id}")).json()
        if body["status"] != "planning":
            return body
        await asyncio.sleep(0.05)
    raise AssertionError(f"session {session_id} is still planning")


async def test_a_session_goes_from_planning_to_awaiting_approval_with_an_optimised_plan(
    postgres_url: str, running_api: Api, small_dataset: GeneratedDataset
) -> None:
    llm = GatedProvider(FakeProvider([READING]))
    async with running_api(postgres_url, llm) as client:
        created = await client.post("/api/sessions", json={"brief": BRIEF})
        session_id = created.json()["session_id"]
        planning = (await client.get(f"/api/sessions/{session_id}")).json()
        llm.gate.set()
        done = await settled(client, session_id)

    assert created.status_code == 202
    assert planning["status"] == "planning"
    assert planning["brief"] == BRIEF
    assert planning["plan_revision"] is None
    assert done["status"] == "awaiting_approval"
    assert done["error"] is None
    request = done["planning_request"]
    assert request["as_of_week"] == HISTORY_WEEKS
    assert request["marketing_budget"] == BUDGET
    assert request["scope"]["regions"] == ["North"]
    assert request["promo_window"] == {"start_week": 54, "end_week": 55}
    revision = done["plan_revision"]
    snacks = set(small_dataset.products.query("category == 'Snacks'")["sku_id"])
    assert revision["number"] == 1
    assert revision["lines"]
    assert sum(line["promo_cost"] for line in revision["lines"]) <= BUDGET
    assert {line["line"]["region"] for line in revision["lines"]} == {"North"}
    assert {line["line"]["sku_id"] for line in revision["lines"]} <= snacks
    assert revision["solver_status"] == "OPTIMAL"
    assert revision["objective"] > 0
    assert all(line["why_chosen"]["reasons"] for line in revision["lines"])
    # Each line compares the mechanisms, its own shown with the line itself (F-02, ADR 0041).
    for line in revision["lines"]:
        [chosen] = [outcome for outcome in line["mechanism_comparison"] if outcome["chosen"]]
        assert chosen["mechanism"] == line["line"]["mechanism"]
        assert chosen["best"]["option"] == line["line"]
        mechanisms = [outcome["mechanism"] for outcome in line["mechanism_comparison"]]
        assert {"PCT_OFF", "FIXED_PRICE"} <= set(mechanisms)
    assert len(revision["not_selected"]) <= 5
    assert all(entry["reasons"] for entry in revision["not_selected"])
    # The stored simulation of the revision (ADR 0042).
    simulation = revision["simulation"]
    assert (simulation["n_runs"], simulation["seed"]) == (200, 0)
    assert [(s["sku_id"], s["region"]) for s in simulation["lines"]] == [
        (line["line"]["sku_id"], line["line"]["region"]) for line in revision["lines"]
    ]
    for simulated in [*simulation["lines"], simulation["total"]]:
        units = simulated["units"]
        assert units["p10"] <= units["p50"] <= units["p90"]
    assert [r["region"] for r in simulation["regions"]] == ["North"]


async def test_a_session_reports_the_constraints_that_bind_its_plan(
    postgres_url: str, running_api: Api
) -> None:
    tight = READING.model_copy(update={"marketing_budget": 300.0})
    async with running_api(postgres_url, FakeProvider([tight])) as client:
        session_id = (await client.post("/api/sessions", json={"brief": BRIEF})).json()[
            "session_id"
        ]
        done = await settled(client, session_id)

    revision = done["plan_revision"]
    assert revision["solver_status"] == "OPTIMAL"
    assert {"kind": "marketing_budget", "source": "brief", "limit": 300.0} in [
        {key: constraint[key] for key in ("kind", "source", "limit")}
        for constraint in revision["binding_constraints"]
    ]
    assert sum(line["promo_cost"] for line in revision["lines"]) <= 300.0


async def test_a_session_without_trained_models_fails_saying_how_to_train(
    postgres_url: str,
) -> None:
    async with api_process(postgres_url, FakeProvider([READING]), None) as client:
        session_id = (await client.post("/api/sessions", json={"brief": BRIEF})).json()[
            "session_id"
        ]
        done = await settled(client, session_id)

    assert done["status"] == "failed"
    assert "make train" in done["error"]


async def test_an_llm_error_fails_the_session(postgres_url: str, running_api: Api) -> None:
    async with running_api(postgres_url, FakeProvider([LLMError("provider down")])) as client:
        session_id = (await client.post("/api/sessions", json={"brief": BRIEF})).json()[
            "session_id"
        ]
        done = await settled(client, session_id)

    assert done["status"] == "failed"
    assert "provider down" in done["error"]
    assert done["plan_revision"] is None


async def test_a_brief_missing_its_budget_fails_the_session_saying_so(
    postgres_url: str, running_api: Api
) -> None:
    unbudgeted = READING.model_copy(update={"marketing_budget": None})
    async with running_api(postgres_url, FakeProvider([unbudgeted])) as client:
        session_id = (await client.post("/api/sessions", json={"brief": BRIEF})).json()[
            "session_id"
        ]
        done = await settled(client, session_id)

    assert done["status"] == "failed"
    assert "marketing budget" in done["error"]


async def test_an_unknown_session_is_404(postgres_url: str) -> None:
    async with api_process(postgres_url, FakeProvider([]), None) as client:
        response = await client.get("/api/sessions/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404


@pytest.mark.parametrize("brief", ["", "   \n ", "x" * 2001], ids=["empty", "blank", "oversized"])
async def test_an_empty_or_oversized_brief_is_422(postgres_url: str, brief: str) -> None:
    llm = FakeProvider([])
    async with api_process(postgres_url, llm, None) as client:
        response = await client.post("/api/sessions", json={"brief": brief})

    assert response.status_code == 422
    assert llm.calls == []


async def test_finished_sessions_survive_a_restart_and_interrupted_ones_fail(
    postgres_url: str,
    running_api: Api,
) -> None:
    async with running_api(postgres_url, FakeProvider([READING])) as client:
        finished_id = (await client.post("/api/sessions", json={"brief": BRIEF})).json()[
            "session_id"
        ]
        finished = await settled(client, finished_id)
    stuck = GatedProvider(FakeProvider([READING]))
    async with running_api(postgres_url, stuck) as client:
        stuck_id = (await client.post("/api/sessions", json={"brief": BRIEF})).json()["session_id"]

    async with running_api(postgres_url, FakeProvider([])) as client:
        after_finished = (await client.get(f"/api/sessions/{finished_id}")).json()
        after_stuck = (await client.get(f"/api/sessions/{stuck_id}")).json()

    assert after_finished == finished
    assert after_stuck["status"] == "failed"
    assert "interrupted" in after_stuck["error"]


async def test_a_brief_that_would_loosen_policy_is_flagged_on_the_plan_revision(
    postgres_url: str, running_api: Api
) -> None:
    loose = READING.model_copy(update={"min_margin": 0.05})
    async with running_api(postgres_url, FakeProvider([loose])) as client:
        session_id = (await client.post("/api/sessions", json={"brief": BRIEF})).json()[
            "session_id"
        ]
        done = await settled(client, session_id)

    revision = done["plan_revision"]
    assert done["planning_request"]["min_margin"] == 0.05
    assert [
        (finding["field"], finding["requested"], finding["applied"])
        for finding in revision["policy_findings"]
    ] == [("min_margin", 0.05, FREE.margin_floor)]
    assert revision["clearance_shortfalls"] == []


class Clearing:
    """Plans every request with a clearance target: the brief cannot carry one until #46."""

    def __init__(self, inner: Planner, target: ClearanceTarget) -> None:
        self.inner = inner
        self.target = target

    async def plan(self, request: PlanningRequest) -> PlanRevision:
        return await self.inner.plan(
            request.model_copy(update={"clearance_targets": (self.target,)})
        )


async def test_an_infeasible_session_exposes_its_binding_constraints_and_relaxation(
    postgres_url: str, running_api: Api, small_dataset: GeneratedDataset
) -> None:
    snapshot = small_dataset.inventory.query(f"snapshot_week == {HISTORY_WEEKS - 1}")
    pooled = pooled_stock(snapshot, small_dataset.stores, FREE).query("region == 'North'")
    snacks = set(small_dataset.products.query("category == 'Snacks'")["sku_id"])
    covered = pooled[pooled["sku_id"].isin(snacks)].sort_values("days_of_cover")
    sku_id = str(covered["sku_id"].iloc[-1])
    # Selling every unit of the Snacks SKU with the most cover in two weeks is out of reach:
    # P90 units must stay within stock, so no brief change helps and company policy binds.
    target = ClearanceTarget(sku_id=sku_id, sell_through=1.0)
    async with running_api(
        postgres_url, FakeProvider([READING]), lambda inner: Clearing(inner, target)
    ) as client:
        session_id = (await client.post("/api/sessions", json={"brief": BRIEF})).json()[
            "session_id"
        ]
        done = await settled(client, session_id)

    assert done["status"] == "awaiting_approval"
    revision = done["plan_revision"]
    assert revision["solver_status"] == "INFEASIBLE"
    assert [
        (c["kind"], c["source"], c["sku_id"], c["region"], c["limit"], c["evidence"])
        for c in revision["binding_constraints"]
    ] == [("clearance_target", "brief", sku_id, "North", 1.0, "infeasible")]
    [shortfall] = revision["clearance_shortfalls"]
    relaxation = revision["relaxation"]
    assert relaxation["policy_binds"] is True
    [change] = relaxation["changes"]
    assert (change["kind"], change["source"], change["sku_id"], change["current"]) == (
        "clearance_target",
        "brief",
        sku_id,
        1.0,
    )
    assert change["relaxed"] is None or change["relaxed"] <= shortfall["expected_sell_through"]
    assert change["change"] > 0


async def test_a_plan_revision_keeps_its_clearance_shortfalls_and_the_briefs_constraints(
    postgres_url: str,
) -> None:
    engine = create_async_engine(postgres_url)
    store = SessionStore(engine)
    request = PlanningRequest(
        as_of_week=HISTORY_WEEKS,
        scope=Scope(regions=(Region.NORTH,), categories=("Snacks",)),
        promo_window=PromoWindow(start_week=HISTORY_WEEKS + 2, end_week=HISTORY_WEEKS + 3),
        marketing_budget=BUDGET,
        clearance_targets=(ClearanceTarget(sku_id="SKU0005", sell_through=0.9),),
        regional_budget_caps={Region.NORTH: 5_000.0},
        kvi_price_tolerance=0.01,
        max_promoted_skus_per_category_per_region=4,
    )
    shortfall = ClearanceShortfall(
        sku_id="SKU0005",
        region=Region.NORTH,
        target=0.9,
        expected_sell_through=0.6,
        shortfall_units=64.8,
    )
    relaxation = Relaxation(
        changes=(
            RelaxedConstraint(
                kind=ConstraintKind.MARKETING_BUDGET,
                current=BUDGET,
                relaxed=22_000.0,
                change=0.1,
            ),
            RelaxedConstraint(
                kind=ConstraintKind.CLEARANCE_TARGET,
                sku_id="SKU0005",
                current=0.9,
                relaxed=0.6,
                change=1 / 3,
                policy_allows=0.6,
            ),
        ),
        policy_binds=True,
        proven=True,
    )
    revision = PlanRevision(
        number=1,
        solver_status=SolveStatus.INFEASIBLE,
        clearance_shortfalls=(shortfall,),
        relaxation=relaxation,
    )
    try:
        session_id = await store.create(BRIEF)
        await store.save_plan(session_id, request, revision)
        saved = await store.get(session_id)
    finally:
        await engine.dispose()

    assert saved is not None
    assert saved.planning_request == request
    assert saved.latest_revision == revision


async def test_a_resimulation_replaces_the_stored_simulation_in_the_session_read_model(
    postgres_url: str, running_api: Api
) -> None:
    async with running_api(postgres_url, FakeProvider([READING])) as client:
        session_id = (await client.post("/api/sessions", json={"brief": BRIEF})).json()[
            "session_id"
        ]
        planned = await settled(client, session_id)
        response = await client.post(f"/api/plans/{session_id}/simulate", json={"n_runs": 300})
        after = (await client.get(f"/api/sessions/{session_id}")).json()

    assert response.status_code == 200
    body = response.json()
    assert (body["session_id"], body["revision_number"]) == (session_id, 1)
    assert body["as_of_week"] == HISTORY_WEEKS
    simulation = body["simulation"]
    assert (simulation["n_runs"], simulation["seed"]) == (300, 0)
    assert planned["plan_revision"]["simulation"]["n_runs"] == 200
    # The same revision now carries the new result; nothing else about it changes (ADR 0043).
    revision = after["plan_revision"]
    assert revision["simulation"] == simulation
    assert {**revision, "simulation": None} == {**planned["plan_revision"], "simulation": None}


async def test_resimulating_an_unknown_plan_is_404(postgres_url: str, running_api: Api) -> None:
    async with running_api(postgres_url, FakeProvider([])) as client:
        response = await client.post(
            "/api/plans/00000000-0000-0000-0000-000000000000/simulate", json={"n_runs": 300}
        )

    assert response.status_code == 404
