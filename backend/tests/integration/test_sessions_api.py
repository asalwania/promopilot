"""The session API over HTTP, with a FakeProvider and the optimising planner on the small
world's fitted models, against real Postgres and the agent graph's Postgres checkpoints (E3
seam 1, E6 seam 5, E8 #44, #46)."""

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

from promopilot.agents import (
    BriefReading,
    GraphTools,
    LLMPricing,
    MemoryCheckpoints,
    OptimisingPlanner,
    PlannedRevision,
    Planner,
    PostgresCheckpoints,
    build_graph,
    graph_state,
)
from promopilot.agents.tools.inventory_status import pooled_stock
from promopilot.api.main import create_app
from promopilot.api.plans import PlanService
from promopilot.api.sessions import SessionService
from promopilot.config import DEFAULT_LLM_PRICES
from promopilot.data import (
    RetailData,
    SessionConflictError,
    SessionStore,
    TraceStore,
    load_dataset,
)
from promopilot.datagen import GeneratedDataset, write
from promopilot.domain import (
    Clarification,
    ClarificationQuestion,
    ClearanceShortfall,
    ClearanceTarget,
    CompanyPolicy,
    ConstraintKind,
    DecisionKind,
    ExplanationSource,
    FallbackReason,
    Mechanism,
    PlanExplanation,
    PlanningRequest,
    PlanRevision,
    PromoWindow,
    QuestionReason,
    Region,
    Relaxation,
    RelaxedConstraint,
    RiskCode,
    RiskFinding,
    Scope,
    SolveStatus,
    Violation,
    ViolationCode,
)
from promopilot.guardrails import RiskThresholds
from promopilot.llm import FakeProvider, LLMError, LLMProvider, Message, ToolSpec, ToolTurn
from promopilot.models.demand import DemandModel
from promopilot.models.registry import ModelKind
from promopilot.models.relations import Relations
from promopilot.optimizer import SolverSettings
from promopilot.simulator import SimulationSettings
from tests.offline import NoModel
from tests.unit.agents.fakes import explainer_down
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

QUIET = RiskThresholds(line_spend_share=1.0)
"""The small world's plans put most of their spend on one line; these API tests are not about
the Critic's risk review (ADR 0051), so it flags no over-concentrated line and makes no LLM
call unless a test asks for the default thresholds."""


@pytest.fixture
def running_api(small_models: tuple[DemandModel, Relations]) -> Api:
    """Starts one API process planning on the small world's fitted models; `planning`
    wraps its planner."""

    def start(
        url: str,
        llm: LLMProvider,
        planning: Callable[[Planner], Planner] | None = None,
        *,
        risk_thresholds: RiskThresholds = QUIET,
    ) -> AbstractAsyncContextManager[AsyncClient]:
        return api_process(url, llm, small_models, planning, risk_thresholds=risk_thresholds)

    return start


@asynccontextmanager
async def api_process(
    url: str,
    llm: LLMProvider,
    models: tuple[DemandModel, Relations] | None,
    planning: Callable[[Planner], Planner] | None = None,
    *,
    risk_thresholds: RiskThresholds = QUIET,
) -> AsyncIterator[AsyncClient]:
    """One API process: its own engine, startup and shutdown, like a uvicorn worker."""
    async with api_app(url, llm, models, planning, risk_thresholds=risk_thresholds) as app:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


@asynccontextmanager
async def api_app(
    url: str,
    llm: LLMProvider,
    models: tuple[DemandModel, Relations] | None,
    planning: Callable[[Planner], Planner] | None = None,
    *,
    trace_poll_interval_s: float = 0.05,
    risk_thresholds: RiskThresholds = QUIET,
) -> AsyncIterator[FastAPI]:
    """The app of one API process, started up; it shuts down on leaving."""
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
    trace = TraceStore(engine)
    sessions = SessionService(
        store=store,
        tools=GraphTools(
            brief_data=data,
            planner=planning(planner) if planning else planner,
            sessions=store,
            policy=FREE,
            trace=trace,
            pricing=LLMPricing(prices=DEFAULT_LLM_PRICES, usd_inr_rate=96.0),
            risk_thresholds=risk_thresholds,
        ),
        llm=llm,
        checkpoints=PostgresCheckpoints(url),
        trace=trace,
        trace_poll_interval_s=trace_poll_interval_s,
    )
    plans = PlanService(
        revisions=store, demand_models=demand, data=data, policy=FREE, defaults=simulation
    )
    app: FastAPI = create_app(
        database_probe=HealthyProbe(), model_status=NoModel(), sessions=sessions, plans=plans
    )
    try:
        async with app.router.lifespan_context(app):
            yield app
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
    llm = GatedProvider(FakeProvider([READING, explainer_down()]))
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
    # The Explainer's LLM was down, so the template explains the revision (ADR 0050).
    explanation = revision["explanation"]
    assert explanation["source"] == "template"
    assert explanation["fallback_reason"] == "llm_unavailable"
    # How the Context agent read the brief (ADR 0048).
    assumed = {a["field"]: a for a in done["assumptions"]}
    assert (assumed["marketing_budget"]["source"], assumed["marketing_budget"]["confidence"]) == (
        "brief",
        1.0,
    )
    assert assumed["min_margin"]["source"] == "default"
    assert (done["questions"], done["clarifications"]) == ([], [])
    assert explanation["summary"].startswith("Plan revision 1.")
    assert len(explanation["rationales"]) == len(revision["lines"])


async def test_a_session_reports_the_constraints_that_bind_its_plan(
    postgres_url: str, running_api: Api
) -> None:
    tight = READING.model_copy(update={"marketing_budget": 300.0})
    async with running_api(postgres_url, FakeProvider([tight, explainer_down()])) as client:
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
    async with api_process(postgres_url, FakeProvider([READING, explainer_down()]), None) as client:
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


# --- clarification (E8 #46, ADR 0048) ---------------------------------------------------------

UNBUDGETED = READING.model_copy(update={"marketing_budget": None})


async def clarifying_session(client: AsyncClient) -> str:
    session_id: str = (await client.post("/api/sessions", json={"brief": BRIEF})).json()[
        "session_id"
    ]
    waiting = await settled(client, session_id)
    assert waiting["status"] == "awaiting_clarification", waiting
    return session_id


async def test_a_brief_missing_its_budget_asks_and_the_answer_resumes_planning(
    postgres_url: str, running_api: Api
) -> None:
    async with running_api(
        postgres_url, FakeProvider([UNBUDGETED, READING, explainer_down()])
    ) as client:
        session_id = await clarifying_session(client)
        waiting = (await client.get(f"/api/sessions/{session_id}")).json()
        answered = await client.post(
            f"/api/sessions/{session_id}/clarify", json={"answers": {"marketing_budget": "₹20k"}}
        )
        done = await settled(client, session_id)

    [question] = waiting["questions"]
    assert (question["id"], question["field"], question["reason"]) == (
        "marketing_budget",
        "marketing_budget",
        "missing",
    )
    assert "budget" in question["question"]
    assert waiting["planning_request"] is None
    assert waiting["plan_revision"] is None
    assert "scope.regions" in {a["field"] for a in waiting["assumptions"]}
    assert answered.status_code == 202, answered.text
    body = answered.json()
    assert body["status"] == "planning"
    assert body["questions"] == []
    assert [(c["question"]["id"], c["answer"]) for c in body["clarifications"]] == [
        ("marketing_budget", "₹20k")
    ]
    assert done["status"] == "awaiting_approval", done
    assert done["planning_request"]["marketing_budget"] == BUDGET
    assert done["plan_revision"]["number"] == 1
    assert done["clarifications"] == body["clarifications"]
    budget = {a["field"]: a for a in done["assumptions"]}["marketing_budget"]
    assert budget["source"] == "brief"


async def test_a_clarification_survives_a_restart_and_resumes_from_its_checkpoint(
    postgres_url: str, running_api: Api
) -> None:
    async with running_api(postgres_url, FakeProvider([UNBUDGETED])) as client:
        session_id = await clarifying_session(client)

    # A new API process: its own engine, checkpointer pool and graph. The session is still
    # waiting (only `planning` sessions fail at startup), and answering resumes it.
    async with running_api(postgres_url, FakeProvider([READING, explainer_down()])) as client:
        waiting = (await client.get(f"/api/sessions/{session_id}")).json()
        answered = await client.post(
            f"/api/sessions/{session_id}/clarify", json={"answers": {"marketing_budget": "₹20k"}}
        )
        done = await settled(client, session_id)

    assert waiting["status"] == "awaiting_clarification"
    assert answered.status_code == 202, answered.text
    assert done["status"] == "awaiting_approval", done
    assert done["plan_revision"]["number"] == 1


async def test_answering_a_session_not_awaiting_clarification_is_409(
    postgres_url: str, running_api: Api
) -> None:
    async with running_api(postgres_url, FakeProvider([READING, explainer_down()])) as client:
        session_id = await planned_session(client)
        response = await client.post(
            f"/api/sessions/{session_id}/clarify", json={"answers": {"marketing_budget": "₹20k"}}
        )
        after = (await client.get(f"/api/sessions/{session_id}")).json()

    assert response.status_code == 409
    assert "awaiting clarification" in response.json()["detail"]
    assert after["status"] == "awaiting_approval"
    assert after["clarifications"] == []


async def test_answering_twice_is_409(postgres_url: str, running_api: Api) -> None:
    llm = GatedProvider(FakeProvider([UNBUDGETED, READING, explainer_down()]))
    llm.gate.set()
    async with running_api(postgres_url, llm) as client:
        session_id = await clarifying_session(client)
        llm.gate.clear()  # hold the re-read, so the session stays `planning`
        first = await client.post(
            f"/api/sessions/{session_id}/clarify", json={"answers": {"marketing_budget": "₹20k"}}
        )
        second = await client.post(
            f"/api/sessions/{session_id}/clarify", json={"answers": {"marketing_budget": "₹30k"}}
        )
        llm.gate.set()
        done = await settled(client, session_id)

    assert first.status_code == 202
    assert second.status_code == 409
    assert [c["answer"] for c in done["clarifications"]] == ["₹20k"]


async def test_answering_an_unknown_session_is_404(postgres_url: str, running_api: Api) -> None:
    async with running_api(postgres_url, FakeProvider([])) as client:
        response = await client.post(
            "/api/sessions/00000000-0000-0000-0000-000000000000/clarify",
            json={"answers": {"marketing_budget": "₹20k"}},
        )

    assert response.status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"answers": {}},
        {"answers": {"marketing_budget": "   "}},
        {"answers": {"marketing_budget": "x" * 2001}},
        {"answers": {"marketing_budget": "₹20k"}, "extra": 1},
        {"answers": {"regions": "North"}},
        {"answers": {"marketing_budget": "₹20k", "regions": "North"}},
    ],
    ids=["no-answers", "empty", "blank", "oversized", "extra-field", "unanswered", "not-asked"],
)
async def test_an_invalid_clarify_body_is_422(
    postgres_url: str, running_api: Api, body: dict[str, object]
) -> None:
    async with running_api(postgres_url, FakeProvider([UNBUDGETED])) as client:
        session_id = await clarifying_session(client)
        response = await client.post(f"/api/sessions/{session_id}/clarify", json=body)
        after = (await client.get(f"/api/sessions/{session_id}")).json()

    assert response.status_code == 422, response.text
    assert after["status"] == "awaiting_clarification"
    assert after["clarifications"] == []


async def test_finished_sessions_survive_a_restart_and_interrupted_ones_fail(
    postgres_url: str,
    running_api: Api,
) -> None:
    async with running_api(postgres_url, FakeProvider([READING, explainer_down()])) as client:
        finished_id = (await client.post("/api/sessions", json={"brief": BRIEF})).json()[
            "session_id"
        ]
        finished = await settled(client, finished_id)
    stuck = GatedProvider(FakeProvider([READING, explainer_down()]))
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
    async with running_api(postgres_url, FakeProvider([loose, explainer_down()])) as client:
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
    # The Context agent flags it too: the floor applies (ADR 0048).
    margin = {a["field"]: a for a in done["assumptions"]}["min_margin"]
    assert margin["flagged"]
    assert margin["value"].startswith("10.0%")


class Clearing:
    """Plans every request with a clearance target: the brief cannot carry one until #46."""

    def __init__(self, inner: Planner, target: ClearanceTarget) -> None:
        self.inner = inner
        self.target = target

    async def plan(self, request: PlanningRequest) -> PlannedRevision:
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
        postgres_url,
        FakeProvider([READING, explainer_down()]),
        lambda inner: Clearing(inner, target),
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
    issue = Violation(
        code=ViolationCode.CLEARANCE_TARGET,
        message="short",
        sku_id="SKU0005",
        region=Region.NORTH,
        actual=0.6,
        limit=0.9,
    )
    risk = RiskFinding(
        code=RiskCode.STOCKOUT_RISK,
        message="SKU0005 in North runs out of stock in 30% of the simulated runs",
        feedback="Promote SKU0005 in North less deeply.",
        sku_id="SKU0005",
        region=Region.NORTH,
        actual=0.3,
        limit=0.2,
    )
    explanation = PlanExplanation(
        summary="Infeasible: SKU0005 reaches 60% of a 90% target.",
        source=ExplanationSource.TEMPLATE,
        fallback_reason=FallbackReason.UNGROUNDED,
    )
    try:
        session_id = await store.create(BRIEF)
        await store.save_revision(session_id, request, revision)
        await store.save_open_issues(session_id, 1, (issue, risk))
        await store.save_explanation(session_id, 1, explanation)
        await store.await_approval(session_id)
        saved = await store.get(session_id)
    finally:
        await engine.dispose()

    assert saved is not None
    assert saved.status == "awaiting_approval"
    assert saved.thread_id == str(session_id)
    assert saved.planning_request == request
    assert saved.latest_revision == revision.model_copy(
        update={"open_issues": (issue, risk), "explanation": explanation}
    )


async def test_a_resimulation_replaces_the_stored_simulation_in_the_session_read_model(
    postgres_url: str, running_api: Api
) -> None:
    async with running_api(postgres_url, FakeProvider([READING, explainer_down()])) as client:
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


# --- approval and rejection (E8 #44, ADR 0046) -------------------------------------------------


async def planned_session(client: AsyncClient) -> str:
    session_id: str = (await client.post("/api/sessions", json={"brief": BRIEF})).json()[
        "session_id"
    ]
    done = await settled(client, session_id)
    assert done["status"] == "awaiting_approval", done
    return session_id


async def test_approval_after_a_restart_resumes_the_graph_from_its_checkpoint(
    postgres_url: str, running_api: Api, small_models: tuple[DemandModel, Relations]
) -> None:
    async with running_api(postgres_url, FakeProvider([READING, explainer_down()])) as client:
        session_id = await planned_session(client)
        planned = (await client.get(f"/api/sessions/{session_id}")).json()

    # A new API process: its own engine, checkpointer pool and agent graph, and an LLM with
    # nothing to say. Approving must resume the graph from the Postgres checkpoint.
    async with running_api(postgres_url, FakeProvider([])) as client:
        approved = await client.post(
            f"/api/sessions/{session_id}/approve", json={"revision_number": 1}
        )
        after = (await client.get(f"/api/sessions/{session_id}")).json()

    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["status"] == "approved"
    assert body["plan_revision"] == planned["plan_revision"]
    [decision] = body["decisions"]
    assert (decision["decision"], decision["revision_number"], decision["reason"]) == (
        "approved",
        1,
        None,
    )
    assert decision["decided_at"]
    assert after == body
    # The graph itself went from the Approval interrupt to Done.
    checkpoints = PostgresCheckpoints(postgres_url)
    try:
        graph = build_graph(
            GraphTools(
                brief_data=NeverRead(),
                planner=NeverPlans(),
                sessions=NeverRecords(),
                policy=FREE,
            ),
            FakeProvider([]),
            await checkpoints.open(),
        )
        state = await graph_state(graph, session_id)
    finally:
        await checkpoints.close()
    assert state is not None
    assert state.paused_at == ()
    assert state.values.approval is not None
    assert state.values.approval.decision is DecisionKind.APPROVED


async def test_a_rejection_keeps_the_session_open_with_its_reason(
    postgres_url: str, running_api: Api
) -> None:
    async with running_api(postgres_url, FakeProvider([READING, explainer_down()])) as client:
        session_id = await planned_session(client)
        rejected = await client.post(
            f"/api/sessions/{session_id}/reject",
            json={"revision_number": 1, "reason": "Too much on Beverages"},
        )
        again = await client.post(
            f"/api/sessions/{session_id}/reject",
            json={"revision_number": 1, "reason": "Still no"},
        )
        approve = await client.post(
            f"/api/sessions/{session_id}/approve", json={"revision_number": 1}
        )
    async with running_api(postgres_url, FakeProvider([])) as client:
        after = (await client.get(f"/api/sessions/{session_id}")).json()

    assert rejected.status_code == 200, rejected.text
    body = rejected.json()
    assert body["status"] == "rejected"
    assert [(d["decision"], d["revision_number"], d["reason"]) for d in body["decisions"]] == [
        ("rejected", 1, "Too much on Beverages")
    ]
    # A rejected revision waits for an amendment (#50): it can be neither rejected again nor
    # approved.
    assert again.status_code == 409
    assert approve.status_code == 409
    assert after == body


async def test_approving_twice_is_409_and_keeps_one_approval(
    postgres_url: str, running_api: Api
) -> None:
    async with running_api(postgres_url, FakeProvider([READING, explainer_down()])) as client:
        session_id = await planned_session(client)
        first = await client.post(
            f"/api/sessions/{session_id}/approve", json={"revision_number": 1}
        )
        second = await client.post(
            f"/api/sessions/{session_id}/approve", json={"revision_number": 1}
        )
        reject = await client.post(
            f"/api/sessions/{session_id}/reject",
            json={"revision_number": 1, "reason": "changed my mind"},
        )
        after = (await client.get(f"/api/sessions/{session_id}")).json()

    assert first.status_code == 200
    assert second.status_code == 409
    assert "approved" in second.json()["detail"]
    assert reject.status_code == 409
    assert [d["decision"] for d in after["decisions"]] == ["approved"]


async def test_deciding_while_planning_is_409(postgres_url: str, running_api: Api) -> None:
    llm = GatedProvider(FakeProvider([READING, explainer_down()]))
    async with running_api(postgres_url, llm) as client:
        session_id = (await client.post("/api/sessions", json={"brief": BRIEF})).json()[
            "session_id"
        ]
        approve = await client.post(
            f"/api/sessions/{session_id}/approve", json={"revision_number": 1}
        )
        reject = await client.post(
            f"/api/sessions/{session_id}/reject", json={"revision_number": 1, "reason": "no"}
        )
        llm.gate.set()
        done = await settled(client, session_id)

    assert approve.status_code == 409
    assert "planning" in approve.json()["detail"]
    assert reject.status_code == 409
    assert done["status"] == "awaiting_approval"
    assert done["decisions"] == []


async def test_deciding_on_a_revision_that_is_not_the_latest_is_409(
    postgres_url: str, running_api: Api
) -> None:
    async with running_api(postgres_url, FakeProvider([READING, explainer_down()])) as client:
        session_id = await planned_session(client)
        response = await client.post(
            f"/api/sessions/{session_id}/approve", json={"revision_number": 2}
        )
        after = (await client.get(f"/api/sessions/{session_id}")).json()

    assert response.status_code == 409
    assert after["status"] == "awaiting_approval"


async def test_an_infeasible_revision_cannot_be_approved_but_can_be_rejected(
    postgres_url: str, running_api: Api, small_dataset: GeneratedDataset
) -> None:
    snapshot = small_dataset.inventory.query(f"snapshot_week == {HISTORY_WEEKS - 1}")
    pooled = pooled_stock(snapshot, small_dataset.stores, FREE).query("region == 'North'")
    snacks = set(small_dataset.products.query("category == 'Snacks'")["sku_id"])
    covered = pooled[pooled["sku_id"].isin(snacks)].sort_values("days_of_cover")
    target = ClearanceTarget(sku_id=str(covered["sku_id"].iloc[-1]), sell_through=1.0)
    async with running_api(
        postgres_url,
        FakeProvider([READING, explainer_down()]),
        lambda inner: Clearing(inner, target),
    ) as client:
        session_id = await planned_session(client)
        approve = await client.post(
            f"/api/sessions/{session_id}/approve", json={"revision_number": 1}
        )
        reject = await client.post(
            f"/api/sessions/{session_id}/reject",
            json={"revision_number": 1, "reason": "Lower the target"},
        )

    assert approve.status_code == 409
    assert "infeasible" in approve.json()["detail"]
    assert reject.status_code == 200
    assert reject.json()["status"] == "rejected"


class Overspending:
    """Plans as usual, but reports plan facts whose first line costs more than the budget."""

    def __init__(self, inner: Planner) -> None:
        self.inner = inner

    async def plan(self, request: PlanningRequest) -> PlannedRevision:
        planned = await self.inner.plan(request)
        first, *rest = planned.facts.lines
        costly = first.model_copy(update={"promo_cost": request.marketing_budget + 1.0})
        facts = planned.facts.model_copy(update={"lines": (costly, *rest)})
        return PlannedRevision(planned.revision, facts)


async def test_violations_and_risk_findings_the_critic_finds_are_open_issues_on_the_revision(
    postgres_url: str, running_api: Api
) -> None:
    critic_down = LLMError("the Critic's LLM is down in this test")
    async with running_api(
        postgres_url,
        FakeProvider([READING, critic_down, explainer_down()]),
        Overspending,
        risk_thresholds=RiskThresholds(),
    ) as client:
        session_id = await planned_session(client)
        body = (await client.get(f"/api/sessions/{session_id}")).json()

    issues = body["plan_revision"]["open_issues"]
    assert (issues[0]["kind"], issues[0]["code"], issues[0]["limit"]) == (
        "violation",
        "BUDGET",
        BUDGET,
    )
    # The overspending line takes most of the plan's spend; its template feedback stands.
    risks = [issue for issue in issues if issue["kind"] == "risk"]
    assert "OVER_CONCENTRATION" in [risk["code"] for risk in risks]
    assert all(risk["feedback"] for risk in risks)


async def test_deciding_on_an_unknown_session_is_404(postgres_url: str, running_api: Api) -> None:
    unknown = "00000000-0000-0000-0000-000000000000"
    async with running_api(postgres_url, FakeProvider([])) as client:
        approve = await client.post(f"/api/sessions/{unknown}/approve", json={"revision_number": 1})
        reject = await client.post(
            f"/api/sessions/{unknown}/reject", json={"revision_number": 1, "reason": "no"}
        )

    assert (approve.status_code, reject.status_code) == (404, 404)


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("approve", {}),
        ("approve", {"revision_number": 0}),
        ("approve", {"revision_number": 1, "reason": "unexpected"}),
        ("reject", {"revision_number": 1}),
        ("reject", {"revision_number": 1, "reason": "   "}),
        ("reject", {"revision_number": 1, "reason": "x" * 2001}),
    ],
    ids=["no-revision", "revision-zero", "approve-reason", "no-reason", "blank", "oversized"],
)
async def test_an_invalid_decision_body_is_422(
    postgres_url: str, running_api: Api, path: str, body: dict[str, object]
) -> None:
    async with running_api(postgres_url, FakeProvider([READING, explainer_down()])) as client:
        session_id = await planned_session(client)
        response = await client.post(f"/api/sessions/{session_id}/{path}", json=body)
        after = (await client.get(f"/api/sessions/{session_id}")).json()

    assert response.status_code == 422
    assert after["status"] == "awaiting_approval"


async def test_an_approved_plan_cannot_be_resimulated(postgres_url: str, running_api: Api) -> None:
    async with running_api(postgres_url, FakeProvider([READING, explainer_down()])) as client:
        session_id = await planned_session(client)
        await client.post(f"/api/sessions/{session_id}/approve", json={"revision_number": 1})
        response = await client.post(f"/api/plans/{session_id}/simulate", json={"n_runs": 300})

    assert response.status_code == 409
    assert "approved" in response.json()["detail"]


async def test_the_store_refuses_a_decision_the_session_cannot_take(postgres_url: str) -> None:
    engine = create_async_engine(postgres_url)
    store = SessionStore(engine)
    request = PlanningRequest(
        as_of_week=HISTORY_WEEKS,
        scope=Scope(regions=(Region.NORTH,), categories=("Snacks",)),
        promo_window=PromoWindow(start_week=HISTORY_WEEKS + 2, end_week=HISTORY_WEEKS + 3),
        marketing_budget=BUDGET,
    )
    try:
        session_id = await store.create(BRIEF)
        await store.save_revision(session_id, request, PlanRevision(number=1))
        with pytest.raises(SessionConflictError):  # still planning
            await store.record_decision(session_id, DecisionKind.APPROVED, 1, None)
        await store.await_approval(session_id)
        with pytest.raises(SessionConflictError):  # not the latest revision
            await store.record_decision(session_id, DecisionKind.APPROVED, 2, None)
        decided = await store.record_decision(session_id, DecisionKind.REJECTED, 1, "no")
        await store.await_approval(session_id)  # a rejected session is not reopened
        saved = await store.get(session_id)
    finally:
        await engine.dispose()

    assert saved is not None
    assert saved.status == "rejected"
    assert saved.decisions == (decided,)


async def test_the_store_keeps_answers_only_for_a_session_awaiting_clarification(
    postgres_url: str,
) -> None:
    engine = create_async_engine(postgres_url)
    store = SessionStore(engine)
    question = ClarificationQuestion(
        id="marketing_budget",
        field="marketing_budget",
        question="What marketing budget?",
        reason=QuestionReason.MISSING,
    )
    answered = (Clarification(question=question, answer="₹20k"),)
    try:
        session_id = await store.create(BRIEF)
        with pytest.raises(SessionConflictError):  # still planning
            await store.answer_clarifications(session_id, answered)
        await store.await_clarification(session_id, (question,))
        waiting = await store.get(session_id)
        await store.answer_clarifications(session_id, answered)
        with pytest.raises(SessionConflictError):  # answered already
            await store.answer_clarifications(session_id, answered)
        saved = await store.get(session_id)
    finally:
        await engine.dispose()

    assert waiting is not None
    assert (waiting.status, waiting.questions) == ("awaiting_clarification", (question,))
    assert saved is not None
    assert (saved.status, saved.questions, saved.clarifications) == ("planning", (), answered)


async def test_without_checkpoints_a_new_session_is_503(postgres_url: str) -> None:
    engine = create_async_engine(postgres_url)
    store = SessionStore(engine)
    sessions = SessionService(
        store=store,
        tools=GraphTools(
            brief_data=RetailData(engine), planner=NeverPlans(), sessions=store, policy=FREE
        ),
        llm=FakeProvider([]),
        checkpoints=BrokenCheckpoints(),
        trace=TraceStore(engine),
    )
    app = create_app(database_probe=HealthyProbe(), model_status=NoModel(), sessions=sessions)
    try:
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.post("/api/sessions", json={"brief": BRIEF})
    finally:
        await engine.dispose()

    assert response.status_code == 503


class BrokenCheckpoints(MemoryCheckpoints):
    async def open(self) -> Any:
        raise OSError("checkpoint database unreachable")


class NeverPlans:
    async def plan(self, request: PlanningRequest) -> PlannedRevision:
        raise AssertionError("never plans")


class NeverRead:
    async def products(self) -> Any:
        raise AssertionError("never read")

    async def calendar(self) -> Any:
        raise AssertionError("never read")

    async def default_as_of_week(self) -> int:
        raise AssertionError("never read")

    async def stores(self) -> Any:
        raise AssertionError("never read")

    async def inventory(self, as_of_week: int) -> Any:
        raise AssertionError("never read")

    async def latest_competitor_prices(self, as_of_week: int) -> Any:
        raise AssertionError("never read")


class NeverRecords:
    async def save_assumptions(self, *args: object) -> None:
        raise AssertionError("never records")

    async def save_revision(self, *args: object) -> None:
        raise AssertionError("never records")

    async def save_open_issues(self, *args: object) -> None:
        raise AssertionError("never records")

    async def save_explanation(self, *args: object) -> None:
        raise AssertionError("never records")

    async def await_approval(self, session_id: object) -> None:
        raise AssertionError("never records")

    async def record_decision(self, *args: object) -> Any:
        raise AssertionError("never records")
