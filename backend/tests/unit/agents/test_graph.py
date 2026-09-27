"""The agent graph (SPEC §9.6, #44, ADR 0046), driven with a FakeProvider and a scripted
planner: the routes it takes, the state it keeps and what it records for the session."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pandas as pd
import pytest
from langgraph.checkpoint.memory import InMemorySaver

from promopilot.agents import (
    BriefError,
    BriefReading,
    GraphTools,
    PlannedRevision,
    build_graph,
    checkpoint_serializer,
    graph_state,
    resume_with_decision,
    start_planning,
)
from promopilot.datagen import GeneratedDataset
from promopilot.domain import (
    CompanyPolicy,
    DecisionKind,
    Mechanism,
    PlanDecision,
    PlanExplanation,
    PlanLine,
    PlanningRequest,
    PlanRevision,
    PlanRevisionLine,
    Region,
    SolveStatus,
    TargetSegment,
    Violation,
    ViolationCode,
)
from promopilot.guardrails import LineFacts, PlanFacts, SkuFacts
from promopilot.llm import FakeProvider
from tests.unit.agents.fakes import InMemoryRetailData, explainer_down

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
BRIEF = "Snacks push in the North, ₹20k, weeks 54-55"
POLICY = CompanyPolicy()


def planned(promo_cost: float = 1_500.0) -> PlannedRevision:
    """Plan revision 1 with one line; a promo cost above the budget breaks it."""
    line = PlanLine(
        sku_id="SKU0001",
        region=Region.NORTH,
        mechanism=Mechanism.PCT_OFF,
        depth_pct=20,
        duration_weeks=2,
        start_week=HISTORY_WEEKS + 2,
        target_segment=TargetSegment.ALL_CUSTOMERS,
    )
    revision = PlanRevision(
        number=1,
        lines=(
            PlanRevisionLine(
                line=line,
                expected_units=400.0,
                promo_cost=promo_cost,
                expected_incremental_profit=6_250.0,
            ),
        ),
        solver_status=SolveStatus.OPTIMAL,
        objective=6_250.0,
    )
    facts = PlanFacts(
        lines=(
            LineFacts(
                line=line,
                anchor=SkuFacts(
                    category="Snacks", base_price=100.0, unit_cost=40.0, overstocked=False
                ),
                expected_units=400.0,
                p90_units=450.0,
                available_stock=1_000.0,
                expected_revenue=32_000.0,
                expected_gross_profit=16_000.0,
                promo_cost=promo_cost,
            ),
        ),
    )
    return PlannedRevision(revision=revision, facts=facts)


class ScriptedPlanner:
    def __init__(self, result: PlannedRevision) -> None:
        self.result = result
        self.requests: list[PlanningRequest] = []

    async def plan(self, request: PlanningRequest) -> PlannedRevision:
        self.requests.append(request)
        return self.result


class RecordedSessions:
    """What the graph records for its sessions, in memory, like `SessionStore` would."""

    def __init__(self) -> None:
        self.status: dict[UUID, str] = {}
        self.revisions: dict[UUID, PlanRevision] = {}
        self.open_issues: dict[tuple[UUID, int], tuple[Violation, ...]] = {}
        self.explanations: dict[tuple[UUID, int], PlanExplanation] = {}
        self.decisions: list[PlanDecision] = []

    async def save_revision(
        self, session_id: UUID, request: PlanningRequest, revision: PlanRevision
    ) -> None:
        self.revisions[session_id] = revision

    async def save_open_issues(
        self, session_id: UUID, revision_number: int, issues: tuple[Violation, ...]
    ) -> None:
        self.open_issues[session_id, revision_number] = issues

    async def save_explanation(
        self, session_id: UUID, revision_number: int, explanation: PlanExplanation
    ) -> None:
        self.explanations[session_id, revision_number] = explanation

    async def record_decision(
        self,
        session_id: UUID,
        decision: DecisionKind,
        revision_number: int,
        reason: str | None,
    ) -> PlanDecision:
        self.status[session_id] = decision.value
        recorded = PlanDecision(
            decision=decision,
            revision_number=revision_number,
            reason=reason,
            decided_at=datetime(2026, 9, 28, tzinfo=UTC),
        )
        self.decisions.append(recorded)
        return recorded


@pytest.fixture
def data(small_dataset: GeneratedDataset) -> InMemoryRetailData:
    return InMemoryRetailData(small_dataset)


@pytest.fixture
def sessions() -> RecordedSessions:
    return RecordedSessions()


@pytest.fixture
def checkpointer() -> InMemorySaver:
    return InMemorySaver(serde=checkpoint_serializer())


def tools(
    data: InMemoryRetailData, sessions: RecordedSessions, result: PlannedRevision | None = None
) -> GraphTools:
    return GraphTools(
        brief_data=data,
        planner=ScriptedPlanner(result or planned()),
        sessions=sessions,
        policy=POLICY,
    )


async def test_a_passing_plan_goes_critic_then_explainer_then_waits_for_approval(
    data: InMemoryRetailData, sessions: RecordedSessions, checkpointer: InMemorySaver
) -> None:
    graph = build_graph(
        tools(data, sessions), FakeProvider([READING, explainer_down()]), checkpointer
    )
    session_id = uuid4()

    route = await start_planning(graph, str(session_id), session_id, BRIEF)

    assert route == ["context", "planner", "critic", "explainer", "approval"]
    state = await graph_state(graph, str(session_id))
    assert state is not None
    assert state.paused_at == ("approval",)
    values = state.values
    assert values.request is not None
    assert values.request.marketing_budget == BUDGET
    assert values.plan == planned().revision
    assert values.critic_findings == ()
    assert values.explanations is not None
    assert values.explanations.summary
    assert len(values.explanations.rationales) == 1
    assert sessions.explanations[session_id, 1] == values.explanations
    assert values.approval is None
    assert sessions.revisions[session_id] == planned().revision
    assert sessions.open_issues[session_id, 1] == ()
    assert sessions.decisions == []


async def test_violations_are_kept_as_open_issues_and_the_plan_still_goes_for_approval(
    data: InMemoryRetailData, sessions: RecordedSessions, checkpointer: InMemorySaver
) -> None:
    over_budget = planned(promo_cost=BUDGET + 5_000.0)
    graph = build_graph(
        tools(data, sessions, over_budget), FakeProvider([READING, explainer_down()]), checkpointer
    )
    session_id = uuid4()

    route = await start_planning(graph, str(session_id), session_id, BRIEF)

    assert route == ["context", "planner", "critic", "explainer", "approval"]
    state = await graph_state(graph, str(session_id))
    assert state is not None
    [violation] = state.values.critic_findings
    assert violation.code is ViolationCode.BUDGET
    assert sessions.open_issues[session_id, 1] == (violation,)


async def test_approving_records_the_decision_and_reaches_done(
    data: InMemoryRetailData, sessions: RecordedSessions, checkpointer: InMemorySaver
) -> None:
    graph = build_graph(
        tools(data, sessions), FakeProvider([READING, explainer_down()]), checkpointer
    )
    session_id = uuid4()
    await start_planning(graph, str(session_id), session_id, BRIEF)

    route = await resume_with_decision(
        graph, str(session_id), DecisionKind.APPROVED, revision_number=1, reason=None
    )

    assert route == ["approval", "done"]
    state = await graph_state(graph, str(session_id))
    assert state is not None
    assert state.paused_at == ()
    assert state.values.approval == sessions.decisions[0]
    assert [(d.decision, d.revision_number, d.reason) for d in sessions.decisions] == [
        (DecisionKind.APPROVED, 1, None)
    ]
    assert sessions.status[session_id] == "approved"


async def test_rejecting_records_the_reason_and_waits_at_approval_again(
    data: InMemoryRetailData, sessions: RecordedSessions, checkpointer: InMemorySaver
) -> None:
    graph = build_graph(
        tools(data, sessions), FakeProvider([READING, explainer_down()]), checkpointer
    )
    session_id = uuid4()
    await start_planning(graph, str(session_id), session_id, BRIEF)

    route = await resume_with_decision(
        graph, str(session_id), DecisionKind.REJECTED, revision_number=1, reason="Too deep in West"
    )

    assert route == ["approval", "approval"]
    state = await graph_state(graph, str(session_id))
    assert state is not None
    assert state.paused_at == ("approval",)
    assert state.values.approval is not None
    assert state.values.approval.reason == "Too deep in West"
    assert sessions.status[session_id] == "rejected"
    assert [(d.decision, d.reason) for d in sessions.decisions] == [
        (DecisionKind.REJECTED, "Too deep in West")
    ]


async def test_a_new_graph_on_the_same_checkpointer_resumes_where_the_old_one_paused(
    data: InMemoryRetailData, sessions: RecordedSessions, checkpointer: InMemorySaver
) -> None:
    first = build_graph(
        tools(data, sessions), FakeProvider([READING, explainer_down()]), checkpointer
    )
    session_id = uuid4()
    await start_planning(first, str(session_id), session_id, BRIEF)

    # A rebuilt app: a new graph, a new planner and an LLM with nothing left to say.
    planner = ScriptedPlanner(planned())
    rebuilt = build_graph(
        GraphTools(brief_data=data, planner=planner, sessions=sessions, policy=POLICY),
        FakeProvider([]),
        checkpointer,
    )
    route = await resume_with_decision(
        rebuilt, str(session_id), DecisionKind.APPROVED, revision_number=1, reason=None
    )

    assert route == ["approval", "done"]
    assert planner.requests == []
    state = await graph_state(rebuilt, str(session_id))
    assert state is not None
    assert state.values.plan == planned().revision


async def test_a_brief_the_context_agent_cannot_read_fails_the_run(
    data: InMemoryRetailData, sessions: RecordedSessions, checkpointer: InMemorySaver
) -> None:
    unbudgeted = READING.model_copy(update={"marketing_budget": None})
    graph = build_graph(tools(data, sessions), FakeProvider([unbudgeted]), checkpointer)
    session_id = uuid4()

    with pytest.raises(BriefError, match="marketing budget"):
        await start_planning(graph, str(session_id), session_id, BRIEF)

    assert sessions.revisions == {}


async def test_an_unknown_thread_has_no_state(checkpointer: InMemorySaver) -> None:
    graph = build_graph(
        GraphTools(
            brief_data=NoData(),
            planner=ScriptedPlanner(planned()),
            sessions=RecordedSessions(),
            policy=POLICY,
        ),
        FakeProvider([]),
        checkpointer,
    )

    assert await graph_state(graph, "no-such-thread") is None


class NoData:
    async def products(self) -> pd.DataFrame:
        raise AssertionError("never read")

    async def calendar(self) -> pd.DataFrame:
        raise AssertionError("never read")

    async def default_as_of_week(self) -> int:
        raise AssertionError("never read")
