"""The agent graph (SPEC §9.6, #44, ADR 0046), driven with a FakeProvider and a scripted
planner: the routes it takes, the state it keeps and what it records for the session."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pandas as pd
import pytest
from langgraph.checkpoint.memory import InMemorySaver

from promopilot.agents import (
    BriefReading,
    DegradedReason,
    GraphTools,
    PlannedRevision,
    build_graph,
    checkpoint_serializer,
    graph_state,
    resume_with_answers,
    resume_with_decision,
    start_planning,
)
from promopilot.datagen import GeneratedDataset
from promopilot.domain import (
    Assumption,
    AssumptionSource,
    CompanyPolicy,
    DecisionKind,
    Mechanism,
    OpenIssue,
    PlanDecision,
    PlanExplanation,
    PlanLine,
    PlanningRequest,
    PlanRevision,
    PlanRevisionLine,
    QuestionReason,
    Region,
    SolveStatus,
    TargetSegment,
    ViolationCode,
)
from promopilot.guardrails import LineFacts, PlanFacts, SkuFacts, plan_limits
from promopilot.llm import FakeProvider, LLMError
from tests.unit.agents.fakes import DownProvider, InMemoryRetailData, explainer_down

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
        self.open_issues: dict[tuple[UUID, int], tuple[OpenIssue, ...]] = {}
        self.explanations: dict[tuple[UUID, int], PlanExplanation] = {}
        self.decisions: list[PlanDecision] = []
        self.assumptions: dict[UUID, tuple[Assumption, ...]] = {}

    async def save_assumptions(self, session_id: UUID, assumptions: tuple[Assumption, ...]) -> None:
        self.assumptions[session_id] = assumptions

    async def save_revision(
        self, session_id: UUID, request: PlanningRequest, revision: PlanRevision
    ) -> None:
        self.revisions[session_id] = revision

    async def save_open_issues(
        self, session_id: UUID, revision_number: int, issues: tuple[OpenIssue, ...]
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


# --- the LLM down at Context: the fallback reading (SF-03, #124, ADR 0053) --------------------

DEMO_BRIEF = (  # cassettes/briefs.json
    "Plan a Diwali promotion for Snacks and Beverages in North and West. Run it for the two "
    "weeks leading up to Diwali, with a marketing budget of ₹2 lakh."
)


async def test_with_the_llm_down_at_context_the_demo_brief_still_reaches_a_plan(
    default_dataset: GeneratedDataset, sessions: RecordedSessions, checkpointer: InMemorySaver
) -> None:
    llm = DownProvider()
    planner = ScriptedPlanner(planned())
    graph = build_graph(
        GraphTools(
            brief_data=InMemoryRetailData(default_dataset),
            planner=planner,
            sessions=sessions,
            policy=POLICY,
        ),
        llm,
        checkpointer,
    )
    session_id = uuid4()

    route = await start_planning(graph, str(session_id), session_id, DEMO_BRIEF)

    assert route == ["context", "planner", "critic", "explainer", "approval"]
    state = await graph_state(graph, str(session_id))
    assert state is not None
    assert state.values.context_degraded is DegradedReason.LLM_UNAVAILABLE
    request = planner.requests[0]
    assert request.scope.regions == (Region.NORTH, Region.WEST)
    assert request.scope.categories == ("Snacks", "Beverages")
    assert (request.promo_window.start_week, request.promo_window.end_week) == (108, 109)
    # Numbers come only from the brief's text: "₹2 lakh".
    assert request.marketing_budget == 200_000.0
    saved = sessions.assumptions[session_id]
    assert saved == state.values.assumptions
    assert saved
    assert all(a.fallback for a in saved)
    assert {a.field: a for a in saved}["marketing_budget"].confidence == 0.7


async def test_with_the_llm_down_a_brief_the_rules_cannot_read_goes_to_clarify_not_failed(
    data: InMemoryRetailData, sessions: RecordedSessions, checkpointer: InMemorySaver
) -> None:
    llm = FakeProvider([LLMError("down"), LLMError("still down"), explainer_down()])
    graph = build_graph(tools(data, sessions), llm, checkpointer)
    session_id = uuid4()

    route = await start_planning(
        graph, str(session_id), session_id, "Something nice for the festive season"
    )

    assert route == ["context", "clarify"]
    paused = await graph_state(graph, str(session_id))
    assert paused is not None
    assert paused.awaits_clarification
    asked = {q.field: q for q in paused.values.questions}
    assert set(asked) == {"scope.regions", "scope.categories", "promo_window", "marketing_budget"}

    # The manager answers while the LLM is still down: the rules read each answer.
    route = await resume_with_answers(
        graph,
        str(session_id),
        {
            asked["scope.regions"].id: "North",
            asked["scope.categories"].id: "Snacks",
            asked["promo_window"].id: "weeks 54-55",
            asked["marketing_budget"].id: "₹20k",
        },
    )

    assert route == ["clarify", "context", "planner", "critic", "explainer", "approval"]
    state = await graph_state(graph, str(session_id))
    assert state is not None
    assert state.values.request is not None
    assert state.values.request.marketing_budget == BUDGET
    assert state.values.context_degraded is DegradedReason.LLM_UNAVAILABLE


# --- the Context agent and the Clarify interrupt (#46, ADR 0048) ------------------------------


async def test_a_missing_budget_routes_to_clarify_and_the_answer_resumes_to_the_planner(
    data: InMemoryRetailData, sessions: RecordedSessions, checkpointer: InMemorySaver
) -> None:
    unbudgeted = READING.model_copy(update={"marketing_budget": None})
    llm = FakeProvider([unbudgeted, READING, explainer_down()])
    planner = ScriptedPlanner(planned())
    graph = build_graph(
        GraphTools(brief_data=data, planner=planner, sessions=sessions, policy=POLICY),
        llm,
        checkpointer,
    )
    session_id = uuid4()

    route = await start_planning(graph, str(session_id), session_id, BRIEF)

    assert route == ["context", "clarify"]
    paused = await graph_state(graph, str(session_id))
    assert paused is not None
    assert paused.awaits_clarification
    assert not paused.awaits_decision
    [question] = paused.values.questions
    assert (question.field, question.reason) == ("marketing_budget", QuestionReason.MISSING)
    assert paused.values.request is None
    assert planner.requests == []
    # What it could read is recorded for the session while it waits.
    assert "scope.regions" in {a.field for a in sessions.assumptions[session_id]}

    route = await resume_with_answers(graph, str(session_id), {question.id: "₹20k"})

    assert route == ["clarify", "context", "planner", "critic", "explainer", "approval"]
    state = await graph_state(graph, str(session_id))
    assert state is not None
    assert state.paused_at == ("approval",)
    assert state.values.questions == ()
    [answered] = state.values.clarifications
    assert (answered.question, answered.answer) == (question, "₹20k")
    assert planner.requests[0].marketing_budget == BUDGET
    # The re-read saw the answer, as quoted data.
    assert '"₹20k"' in llm.calls[1].messages[1].content
    budget = {a.field: a for a in sessions.assumptions[session_id]}["marketing_budget"]
    assert budget.source is AssumptionSource.BRIEF


async def test_low_confidence_on_the_scope_routes_to_clarify(
    data: InMemoryRetailData, sessions: RecordedSessions, checkpointer: InMemorySaver
) -> None:
    # "snak stuff" matches Snacks at 0.593: below the 0.7 threshold.
    vague = READING.model_copy(update={"categories_phrase": "snak stuff"})
    graph = build_graph(tools(data, sessions), FakeProvider([vague]), checkpointer)
    session_id = uuid4()

    route = await start_planning(graph, str(session_id), session_id, BRIEF)

    assert route == ["context", "clarify"]
    state = await graph_state(graph, str(session_id))
    assert state is not None
    [question] = state.values.questions
    assert (question.field, question.reason) == (
        "scope.categories",
        QuestionReason.LOW_CONFIDENCE,
    )


async def test_an_answer_that_leaves_a_question_open_asks_again(
    data: InMemoryRetailData, sessions: RecordedSessions, checkpointer: InMemorySaver
) -> None:
    unbudgeted = READING.model_copy(update={"marketing_budget": None})
    graph = build_graph(tools(data, sessions), FakeProvider([unbudgeted, unbudgeted]), checkpointer)
    session_id = uuid4()
    await start_planning(graph, str(session_id), session_id, BRIEF)

    route = await resume_with_answers(graph, str(session_id), {"marketing_budget": "not sure"})

    assert route == ["clarify", "context", "clarify"]
    state = await graph_state(graph, str(session_id))
    assert state is not None
    assert state.awaits_clarification
    assert len(state.values.clarifications) == 1
    assert [q.field for q in state.values.questions] == ["marketing_budget"]


async def test_a_margin_below_the_floor_is_planned_at_the_floor_and_flagged(
    data: InMemoryRetailData, sessions: RecordedSessions, checkpointer: InMemorySaver
) -> None:
    loose = READING.model_copy(update={"min_margin": 0.05})
    planner = ScriptedPlanner(planned())
    graph = build_graph(
        GraphTools(brief_data=data, planner=planner, sessions=sessions, policy=POLICY),
        FakeProvider([loose, explainer_down()]),
        checkpointer,
    )
    session_id = uuid4()

    await start_planning(graph, str(session_id), session_id, BRIEF)

    [request] = planner.requests
    assert plan_limits(request, POLICY).min_margin == POLICY.margin_floor
    margin = {a.field: a for a in sessions.assumptions[session_id]}["min_margin"]
    assert margin.flagged
    assert margin.value.startswith("15.0%")


async def test_a_revenue_focused_brief_gets_the_profit_objective_assumption(
    data: InMemoryRetailData, sessions: RecordedSessions, checkpointer: InMemorySaver
) -> None:
    revenue = READING.model_copy(update={"objective_asked": "revenue"})
    graph = build_graph(
        tools(data, sessions), FakeProvider([revenue, explainer_down()]), checkpointer
    )
    session_id = uuid4()

    await start_planning(graph, str(session_id), session_id, BRIEF)

    state = await graph_state(graph, str(session_id))
    assert state is not None
    objective = {a.field: a for a in state.values.assumptions}["objective"]
    assert objective.flagged
    assert "profit" in objective.value


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

    async def stores(self) -> pd.DataFrame:
        raise AssertionError("never read")

    async def inventory(self, as_of_week: int) -> pd.DataFrame:
        raise AssertionError("never read")

    async def latest_competitor_prices(self, as_of_week: int) -> pd.DataFrame:
        raise AssertionError("never read")
