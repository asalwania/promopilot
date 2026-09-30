"""Amending a plan (AG-05, #50, ADR 0052), driven through the agent graph with a
FakeProvider: an amendment resumes the Approval interrupt, the Context agent reads the brief
again with every amendment, and the Planner plans a new round whose plan revision carries its
diff from the previous one and an explanation of what changed."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pandas as pd
import pytest
from langgraph.checkpoint.memory import InMemorySaver

from promopilot.agents import (
    AcceptedRelaxation,
    BriefReading,
    ClearanceAsk,
    GraphTools,
    PlannedRevision,
    Planner,
    acceptable_relaxation,
    approval_refusal,
    build_graph,
    checkpoint_serializer,
    graph_state,
    plan_data,
    relaxation_amendment,
    resume_with_acceptance,
    resume_with_amendment,
    resume_with_answers,
    resume_with_decision,
    start_planning,
)
from promopilot.agents.context import context_messages
from promopilot.agents.state import PlanningState
from promopilot.agents.trace import MemoryTrace
from promopilot.datagen import GeneratedDataset, generate, load_config
from promopilot.domain import (
    CompanyPolicy,
    ConstraintKind,
    DecisionKind,
    DecisionMade,
    Mechanism,
    OpenIssue,
    PlanDecision,
    PlanExplanation,
    PlanLine,
    PlanningRequest,
    PlanRevision,
    PlanRevisionLine,
    Region,
    Relaxation,
    RelaxedConstraint,
    RequestChange,
    SolveStatus,
    TargetSegment,
)
from promopilot.guardrails import (
    LineFacts,
    PlanFacts,
    RiskThresholds,
    SkuFacts,
    check_numeric_grounding,
)
from promopilot.llm import FakeProvider, LLMError, Message
from promopilot.models.demand import DemandModel
from promopilot.models.relations import Relations
from tests.conftest import SMALL_OVERRIDES
from tests.unit.agents.fakes import InMemoryRetailData, explainer_down
from tests.unit.agents.test_graph import POLICY
from tests.unit.agents.test_plan_session import FREE, planner_of

HISTORY_WEEKS = 52  # small_config
PLANNED = ["context", "planner", "critic", "explainer", "approval"]
REPLANNED = ["approval", *PLANNED]
NO_RISK = RiskThresholds(
    line_spend_share=1.0,
    group_spend_share=1.0,
    cannibalisation_share=100.0,
    stockout_probability=1.0,
)
"""These tests are not about the Critic's risk review (ADR 0051): it flags nothing and makes
no LLM call."""


def reading(regions: list[Region], budget: float | None) -> BriefReading:
    return BriefReading(
        regions=regions,
        categories=["Snacks"],
        sku_ids=None,
        promo_start_week=HISTORY_WEEKS + 2,
        promo_end_week=HISTORY_WEEKS + 3,
        marketing_budget=budget,
        min_margin=None,
    )


class Saved:
    """What the graph records, keeping every revision and decision."""

    def __init__(self) -> None:
        self.revisions: list[PlanRevision] = []
        self.requests: list[PlanningRequest] = []
        self.explanations: dict[int, PlanExplanation] = {}
        self.decisions: list[PlanDecision] = []

    async def save_revision(
        self, session_id: UUID, request: PlanningRequest, revision: PlanRevision
    ) -> None:
        self.revisions.append(revision)
        self.requests.append(request)

    async def save_open_issues(
        self, session_id: UUID, revision_number: int, issues: tuple[OpenIssue, ...]
    ) -> None:
        return None

    async def save_explanation(
        self, session_id: UUID, revision_number: int, explanation: PlanExplanation
    ) -> None:
        self.explanations[revision_number] = explanation

    async def save_assumptions(self, *args: object) -> None:
        return None

    async def record_decision(
        self, session_id: UUID, decision: DecisionKind, revision_number: int, reason: str | None
    ) -> PlanDecision:
        recorded = PlanDecision(
            decision=decision,
            revision_number=revision_number,
            reason=reason,
            decided_at=datetime(2026, 9, 28, tzinfo=UTC),
        )
        self.decisions.append(recorded)
        return recorded


class PoolPlanner:
    """Plans like the optimiser would on a fixed pool of options: the most profitable lines in
    the request's regions that fit its budget, one per SKU and region."""

    POOL = (
        ("SKU0001", Region.NORTH, 3_00_000.0, 2_50_000.0),
        ("SKU0002", Region.NORTH, 2_00_000.0, 1_20_000.0),
        ("SKU0001", Region.WEST, 4_00_000.0, 2_00_000.0),
        ("SKU0003", Region.WEST, 1_00_000.0, 60_000.0),
    )

    def __init__(self) -> None:
        self.requests: list[PlanningRequest] = []

    async def plan(self, request: PlanningRequest) -> PlannedRevision:
        self.requests.append(request)
        chosen: list[tuple[str, Region, float, float]] = []
        spent = 0.0
        for option in sorted(self.POOL, key=lambda option: -option[3]):
            _, region, cost, _ = option
            if region in request.scope.regions and spent + cost <= request.marketing_budget:
                chosen.append(option)
                spent += cost
        lines = [
            (
                PlanLine(
                    sku_id=sku_id,
                    region=region,
                    mechanism=Mechanism.PCT_OFF,
                    depth_pct=20,
                    duration_weeks=2,
                    start_week=request.promo_window.start_week,
                    target_segment=TargetSegment.ALL_CUSTOMERS,
                ),
                cost,
                profit,
            )
            for sku_id, region, cost, profit in chosen
        ]
        revision = PlanRevision(
            number=1,
            lines=tuple(
                PlanRevisionLine(
                    line=line,
                    expected_units=4_000.0,
                    promo_cost=cost,
                    expected_incremental_profit=profit,
                )
                for line, cost, profit in lines
            ),
            solver_status=SolveStatus.OPTIMAL,
            objective=sum(profit for _, _, profit in lines),
        )
        facts = PlanFacts(
            lines=tuple(
                LineFacts(
                    line=line,
                    anchor=SkuFacts(
                        category="Snacks", base_price=1_000.0, unit_cost=400.0, overstocked=False
                    ),
                    expected_units=4_000.0,
                    p90_units=4_500.0,
                    available_stock=10_000.0,
                    expected_revenue=32_00_000.0,
                    expected_gross_profit=16_00_000.0,
                    promo_cost=cost,
                )
                for line, cost, _ in lines
            )
        )
        return PlannedRevision(revision=revision, facts=facts)


class Session:
    """One planning session's graph."""

    def __init__(
        self, data: InMemoryRetailData, planner: Planner, llm: FakeProvider, policy: CompanyPolicy
    ) -> None:
        self.saved = Saved()
        self.llm = llm
        self.trace = MemoryTrace()
        self.graph = build_graph(
            GraphTools(
                brief_data=data,
                planner=planner,
                sessions=self.saved,
                policy=policy,
                risk_thresholds=NO_RISK,
                trace=self.trace,
            ),
            llm,
            InMemorySaver(serde=checkpoint_serializer()),
        )
        self.id = uuid4()

    async def state(self) -> PlanningState:
        snapshot = await graph_state(self.graph, str(self.id))
        assert snapshot is not None
        return snapshot.values


async def session(
    data: InMemoryRetailData,
    planner: Planner,
    script: list[Any],
    *,
    policy: CompanyPolicy = POLICY,
    brief: str = "Snacks in North and West, ₹10 lakh, weeks 54-55",
) -> Session:
    """A session planned and paused at Approval."""
    planning = Session(data, planner, FakeProvider(script), policy)
    route = await start_planning(planning.graph, str(planning.id), planning.id, brief)
    assert route == PLANNED
    return planning


@pytest.fixture(scope="module")
def north_and_west() -> GeneratedDataset:
    """The small world with the North and West regions, as the demo brief has."""
    return generate(
        load_config(overrides={**SMALL_OVERRIDES, "regions": ["North", "West"]}), seed=11
    )


@pytest.fixture
def data(north_and_west: GeneratedDataset) -> InMemoryRetailData:
    return InMemoryRetailData(north_and_west)


BOTH = [Region.NORTH, Region.WEST]


async def test_cutting_the_budget_plans_a_new_revision_within_it_with_a_diff(
    data: InMemoryRetailData,
) -> None:
    planning = await session(
        data,
        PoolPlanner(),
        [
            reading(BOTH, 10_00_000.0),
            explainer_down(),
            reading(BOTH, 6_00_000.0),
            explainer_down(),
        ],
    )

    route = await resume_with_amendment(planning.graph, str(planning.id), "cut budget to ₹6 lakh")

    assert route == REPLANNED
    first, second = planning.saved.revisions
    assert (first.number, second.number) == (1, 2)
    assert sum(line.promo_cost for line in first.lines) > 6_00_000.0
    assert sum(line.promo_cost for line in second.lines) <= 6_00_000.0
    diff = second.diff
    assert diff is not None
    assert first.diff is None
    assert diff.from_revision == 1
    assert diff.request_changes == (
        RequestChange(field="marketing_budget", before="₹10 lakh", after="₹6 lakh"),
    )
    assert diff.objective_delta == pytest.approx(
        (second.objective or 0.0) - (first.objective or 0.0)
    )
    assert diff.promo_cost_after <= 6_00_000.0
    state = await planning.state()
    assert state.amendments == ("cut budget to ₹6 lakh",)
    assert state.plan == second
    assert state.request is not None
    assert state.request.marketing_budget == 6_00_000.0
    # The Context agent read the brief again with the amendment, as quoted data.
    context_calls = [call for call in planning.llm.calls if call.schema is BriefReading]
    assert len(context_calls) == 2
    assert "cut budget to ₹6 lakh" in context_calls[1].messages[-1].content


async def test_with_the_llm_down_the_amendment_is_read_by_rules_and_replanned(
    data: InMemoryRetailData,
) -> None:
    planning = await session(
        data,
        PoolPlanner(),
        [
            reading(BOTH, 10_00_000.0),
            explainer_down(),
            LLMError("the Context agent's LLM is down for the amendment"),
            explainer_down(),
        ],
    )

    route = await resume_with_amendment(planning.graph, str(planning.id), "cut budget to ₹6 lakh")

    assert route == REPLANNED
    _, second = planning.saved.revisions
    assert sum(line.promo_cost for line in second.lines) <= 6_00_000.0
    assert second.diff is not None
    assert second.diff.request_changes == (
        RequestChange(field="marketing_budget", before="₹10 lakh", after="₹6 lakh"),
    )
    state = await planning.state()
    assert state.context_degraded is not None
    assert state.request is not None
    assert state.request.marketing_budget == 6_00_000.0
    assert state.request.scope.regions == (Region.NORTH, Region.WEST)
    decisions = [e.payload for e in planning.trace.events if isinstance(e.payload, DecisionMade)]
    assert [d.decision for d in decisions].count("context_fallback") == 1


async def test_dropping_west_removes_its_lines_and_the_diff_lists_them_as_removed(
    data: InMemoryRetailData,
) -> None:
    planning = await session(
        data,
        PoolPlanner(),
        [
            reading(BOTH, 10_00_000.0),
            explainer_down(),
            reading([Region.NORTH], 10_00_000.0),
            explainer_down(),
        ],
    )

    await resume_with_amendment(planning.graph, str(planning.id), "Drop West")

    first, second = planning.saved.revisions
    west = tuple(line for line in first.lines if line.line.region is Region.WEST)
    assert west
    assert all(line.line.region is Region.NORTH for line in second.lines)
    assert second.diff is not None
    assert second.diff.removed == west
    assert second.diff.added == ()
    assert second.diff.request_changes == (
        RequestChange(field="scope.regions", before="North, West", after="North"),
    )


async def test_the_change_explanation_passes_grounding(data: InMemoryRetailData) -> None:
    planning = await session(
        data,
        PoolPlanner(),
        [
            reading(BOTH, 10_00_000.0),
            explainer_down(),
            reading([Region.NORTH], 10_00_000.0),
            explainer_down(),
        ],
    )

    await resume_with_amendment(planning.graph, str(planning.id), "Drop West")

    state = await planning.state()
    explanation = state.explanations
    assert explanation is not None
    assert explanation.changes is not None
    assert planning.saved.explanations[2] == explanation
    assert "Removed: SKU0001 in West, SKU0003 in West." in explanation.changes
    plan, request = state.plan, state.request
    assert plan is not None
    assert request is not None
    view = plan_data(plan, request=request, policy=POLICY)
    assert check_numeric_grounding(explanation.changes, view).grounded


async def test_a_rejected_revision_accepts_an_amendment_and_the_rejection_is_kept(
    data: InMemoryRetailData,
) -> None:
    planning = await session(
        data,
        PoolPlanner(),
        [
            reading(BOTH, 10_00_000.0),
            explainer_down(),
            reading(BOTH, 6_00_000.0),
            explainer_down(),
        ],
    )
    await resume_with_decision(
        planning.graph,
        str(planning.id),
        DecisionKind.REJECTED,
        revision_number=1,
        reason="Too much spend",
    )

    route = await resume_with_amendment(planning.graph, str(planning.id), "cut budget to ₹6 lakh")

    assert route == REPLANNED
    assert [revision.number for revision in planning.saved.revisions] == [1, 2]
    assert [(d.decision, d.revision_number) for d in planning.saved.decisions] == [
        (DecisionKind.REJECTED, 1)
    ]
    state = await planning.state()
    assert state.approval is None  # no decision on revision 2 yet
    decisions = [e.payload for e in planning.trace.events if isinstance(e.payload, DecisionMade)]
    assert any(d.decision == "amended" and "cut budget to ₹6 lakh" in d.summary for d in decisions)


async def test_an_amendment_starts_a_new_planning_round(data: InMemoryRetailData) -> None:
    planning = await session(
        data,
        PoolPlanner(),
        [
            reading(BOTH, 10_00_000.0),
            explainer_down(),
            reading(BOTH, 6_00_000.0),
            explainer_down(),
        ],
    )

    await resume_with_amendment(planning.graph, str(planning.id), "cut budget to ₹6 lakh")

    state = await planning.state()
    [attempt] = state.attempts  # the new round's only attempt, not the first round's too
    assert state.plan is not None
    assert attempt.plan.lines == state.plan.lines
    assert state.iteration == 2


async def test_each_amendment_numbers_the_next_revision_and_diffs_it_from_the_last(
    data: InMemoryRetailData,
) -> None:
    planning = await session(
        data,
        PoolPlanner(),
        [
            reading(BOTH, 10_00_000.0),
            explainer_down(),
            reading(BOTH, 6_00_000.0),
            explainer_down(),
            reading([Region.NORTH], 6_00_000.0),
            explainer_down(),
        ],
    )

    await resume_with_amendment(planning.graph, str(planning.id), "cut budget to ₹6 lakh")
    await resume_with_amendment(planning.graph, str(planning.id), "Drop West")

    _, second, third = planning.saved.revisions
    assert third.number == 3
    assert third.diff is not None
    assert third.diff.from_revision == 2
    assert third.diff.request_changes == (
        RequestChange(field="scope.regions", before="North, West", after="North"),
    )
    state = await planning.state()
    assert state.amendments == ("cut budget to ₹6 lakh", "Drop West")
    context_calls = [call for call in planning.llm.calls if call.schema is BriefReading]
    assert "Drop West" in context_calls[2].messages[-1].content
    assert "cut budget to ₹6 lakh" in context_calls[2].messages[-1].content
    assert second.number == 2


async def test_an_amendment_that_leaves_a_critical_field_open_asks_before_planning(
    data: InMemoryRetailData,
) -> None:
    planning = await session(
        data,
        PoolPlanner(),
        [
            reading(BOTH, 10_00_000.0),
            explainer_down(),
            reading(BOTH, None),
            reading(BOTH, 6_00_000.0),
            explainer_down(),
        ],
    )

    route = await resume_with_amendment(planning.graph, str(planning.id), "rethink the budget")

    assert route == ["approval", "context", "clarify"]
    state = await planning.state()
    assert [q.id for q in state.questions] == ["marketing_budget"]
    answered = await resume_with_answers(
        planning.graph, str(planning.id), {"marketing_budget": "₹6 lakh"}
    )
    assert answered == ["clarify", *PLANNED]
    assert [revision.number for revision in planning.saved.revisions] == [1, 2]


async def test_the_optimiser_plans_an_amended_budget_and_scope_on_the_small_world(
    small_dataset: GeneratedDataset, small_models: tuple[DemandModel, Relations]
) -> None:
    data = InMemoryRetailData(small_dataset)
    both = [Region.NORTH, Region.SOUTH]
    planning = await session(
        data,
        planner_of(small_models, data, FREE),
        [
            reading(both, 20_000.0),
            explainer_down(),
            reading(both, 6_000.0),
            explainer_down(),
            reading([Region.NORTH], 6_000.0),
            explainer_down(),
        ],
        policy=FREE,
        brief="Snacks in North and South, ₹20k, weeks 54-55",
    )

    await resume_with_amendment(planning.graph, str(planning.id), "cut budget to ₹6,000")
    await resume_with_amendment(planning.graph, str(planning.id), "drop South")

    first, second, third = planning.saved.revisions
    assert sum(line.promo_cost for line in first.lines) > 6_000.0
    assert sum(line.promo_cost for line in second.lines) <= 6_000.0 + 0.01
    assert second.diff is not None
    assert second.diff.promo_cost_delta < 0
    south = tuple(line for line in second.lines if line.line.region is Region.SOUTH)
    assert south
    assert third.diff is not None
    assert third.diff.removed == south
    assert all(line.line.region is Region.NORTH for line in third.lines)


# How the Context agent is asked to read amendments.


def messages(amendments: tuple[str, ...]) -> list[Message]:
    return context_messages(
        "Snacks in North and West, ₹10 lakh, weeks 54-55",
        as_of_week=HISTORY_WEEKS,
        as_of_date="2025-12-29",
        table=pd.DataFrame(
            {
                "week_id": [54],
                "week_start": ["2026-01-12"],
                "region": ["North"],
                "holiday_name": [None],
            }
        ),
        regions=["North", "West"],
        categories=["Snacks"],
        amendments=amendments,
    )


def test_amendments_come_with_rules_on_reading_them_and_a_brief_without_is_asked_as_before() -> (
    None
):
    plain = messages(())
    amended = messages(("Drop West",))

    assert "Amendments" not in plain[0].content
    assert amended[0].content.startswith(plain[0].content)
    rules = amended[0].content.removeprefix(plain[0].content)
    assert "regions_phrase" in rules
    assert "after the amendments" in rules
    assert '"Drop West"' in amended[1].content


# Accepting a relaxation (ADR 0044) as an amendment.


def test_a_relaxation_is_accepted_as_an_amendment_stating_each_change_exactly() -> None:
    relaxation = Relaxation(
        changes=(
            RelaxedConstraint(
                kind=ConstraintKind.MARKETING_BUDGET,
                current=20_000.0,
                relaxed=20_344.46,
                change=0.017,
            ),
            RelaxedConstraint(
                kind=ConstraintKind.REGIONAL_BUDGET,
                region=Region.NORTH,
                current=9_000.0,
                relaxed=9_500.0,
                change=0.0556,
            ),
            RelaxedConstraint(
                kind=ConstraintKind.MINIMUM_MARGIN, current=0.3, relaxed=0.285, change=0.05
            ),
            RelaxedConstraint(
                kind=ConstraintKind.MAX_PROMOTED_SKUS, current=4.0, relaxed=5.0, change=0.25
            ),
            RelaxedConstraint(
                kind=ConstraintKind.KVI_PRICE_TOLERANCE, current=0.02, relaxed=None, change=1.0
            ),
            RelaxedConstraint(
                kind=ConstraintKind.CLEARANCE_TARGET,
                sku_id="SKU0029",
                current=0.9,
                relaxed=0.7027,
                change=0.219,
            ),
            RelaxedConstraint(
                kind=ConstraintKind.CLEARANCE_TARGET,
                sku_id="SKU0030",
                current=0.5,
                relaxed=None,
                change=1.0,
            ),
        ),
        policy_binds=False,
        proven=True,
    )

    assert relaxation_amendment(relaxation) == (
        "Accept the smallest relaxation: raise the marketing budget to ₹20,344.46; "
        "raise the budget cap for North to ₹9,500.00; lower the minimum margin to 28.50%; "
        "raise the cap on promoted SKUs per category and region to 5; "
        "turn off the KVI price tolerance; "
        "lower the clearance target for SKU0029 to 70.27% sell-through; "
        "drop the clearance target for SKU0030."
    )


# Accepting a relaxation in code (ADR 0083).

NAMKEEN = ClearanceAsk(products="150g namkeen packs", sell_through=0.6)
"""SKU0001 and SKU0002 on the small world, as "400g namkeen packs" is two SKUs in the demo."""
SKU0002 = Relaxation(
    changes=(
        RelaxedConstraint(
            kind=ConstraintKind.CLEARANCE_TARGET,
            sku_id="SKU0002",
            current=0.6,
            relaxed=0.5986,
            change=0.0023,
        ),
    ),
    policy_binds=True,
    proven=True,
)


def clearing(regions: list[Region], budget: float) -> BriefReading:
    return reading(regions, budget).model_copy(update={"clearance": [NAMKEEN]})


def targets_of(request: PlanningRequest | None) -> list[tuple[str, float]]:
    assert request is not None
    return [(t.sku_id, t.sell_through) for t in request.clearance_targets]


async def test_accepting_a_relaxation_for_one_sku_leaves_every_other_sku_target_unchanged(
    data: InMemoryRetailData,
) -> None:
    planning = await session(
        data,
        PoolPlanner(),
        [
            clearing(BOTH, 10_00_000.0),
            explainer_down(),
            clearing(BOTH, 10_00_000.0),
            explainer_down(),
        ],
    )
    assert targets_of((await planning.state()).request) == [("SKU0001", 0.6), ("SKU0002", 0.6)]

    route = await resume_with_acceptance(planning.graph, str(planning.id), SKU0002)

    assert route == REPLANNED
    state = await planning.state()
    assert targets_of(state.request) == [("SKU0001", 0.6), ("SKU0002", 0.5986)]
    assert state.amendments == ()
    assert state.accepted == (AcceptedRelaxation(revision_number=1, relaxation=SKU0002),)
    # The LLM never reads the accepted text (#165): with no other amendment the brief is asked
    # exactly as the first time, so its recorded answer replays.
    context_calls = [call for call in planning.llm.calls if call.schema is BriefReading]
    assert len(context_calls) == 2
    assert context_calls[1].messages == context_calls[0].messages
    [_, second] = planning.saved.revisions
    assert second.number == 2
    assert second.diff is not None
    assert [change.field for change in second.diff.request_changes] == ["clearance_targets"]
    assumed = [a.value for a in state.assumptions if a.field == "clearance_targets"]
    assert assumed[-1] == "59.86% sell-through for SKU0002"
    decisions = [e.payload for e in planning.trace.events if isinstance(e.payload, DecisionMade)]
    assert [d.summary for d in decisions if d.decision == "amended"] == [
        "Plan revision 1 was amended: Accept the smallest relaxation: lower the clearance "
        "target for SKU0002 to 59.86% sell-through."
    ]


async def test_a_later_amendment_is_read_by_the_llm_and_the_accepted_relaxation_still_holds(
    data: InMemoryRetailData,
) -> None:
    planning = await session(
        data,
        PoolPlanner(),
        [
            clearing(BOTH, 10_00_000.0),
            explainer_down(),
            clearing(BOTH, 10_00_000.0),
            explainer_down(),
            clearing(BOTH, 6_00_000.0),
            explainer_down(),
        ],
    )
    await resume_with_acceptance(planning.graph, str(planning.id), SKU0002)

    await resume_with_amendment(planning.graph, str(planning.id), "cut budget to ₹6 lakh")

    state = await planning.state()
    assert state.request is not None
    assert state.request.marketing_budget == 6_00_000.0
    assert targets_of(state.request) == [("SKU0001", 0.6), ("SKU0002", 0.5986)]
    context_calls = [call for call in planning.llm.calls if call.schema is BriefReading]
    read = context_calls[-1].messages[-1].content
    assert "cut budget to ₹6 lakh" in read
    assert "Accept the smallest relaxation" not in read


async def test_with_the_llm_down_an_accepted_relaxation_is_still_applied(
    data: InMemoryRetailData,
) -> None:
    # The rules cannot read an accepted relaxation's text (ADR 0076 D8); they no longer need to.
    budget = Relaxation(
        changes=(
            RelaxedConstraint(
                kind=ConstraintKind.MARKETING_BUDGET,
                current=10_00_000.0,
                relaxed=12_00_000.0,
                change=0.2,
            ),
        ),
        policy_binds=False,
        proven=True,
    )
    planning = await session(
        data,
        PoolPlanner(),
        [
            reading(BOTH, 10_00_000.0),
            explainer_down(),
            LLMError("the Context agent's LLM is down for the accepted relaxation"),
            explainer_down(),
        ],
    )

    route = await resume_with_acceptance(planning.graph, str(planning.id), budget)

    assert route == REPLANNED
    state = await planning.state()
    assert state.context_degraded is not None
    assert state.questions == ()
    assert state.request is not None
    assert state.request.marketing_budget == 12_00_000.0


# What the API and the recorder refuse alike (ADR 0046 D10, ADR 0052 D7, ADR 0070).

CLEARANCE = Relaxation(
    changes=(
        RelaxedConstraint(
            kind=ConstraintKind.CLEARANCE_TARGET,
            sku_id="SKU0006",
            current=0.6,
            relaxed=0.5986,
            change=0.0023,
        ),
    ),
    policy_binds=True,
    proven=True,
)


@pytest.mark.parametrize(
    ("status", "relaxation", "refusal"),
    [
        (SolveStatus.OPTIMAL, None, None),
        (SolveStatus.FEASIBLE, CLEARANCE, None),
        (
            SolveStatus.INFEASIBLE,
            CLEARANCE,
            "plan revision 3 is infeasible: amend the brief with its relaxation before approving",
        ),
    ],
)
def test_only_an_infeasible_revision_is_refused_approval(
    status: SolveStatus, relaxation: Relaxation | None, refusal: str | None
) -> None:
    revision = PlanRevision(number=3, solver_status=status, relaxation=relaxation)

    assert approval_refusal(revision) == refusal


def test_only_a_relaxation_with_changes_can_be_accepted() -> None:
    nothing = CLEARANCE.model_copy(update={"changes": ()})

    assert acceptable_relaxation(PlanRevision(number=3, relaxation=CLEARANCE)) == CLEARANCE
    assert acceptable_relaxation(PlanRevision(number=3, relaxation=nothing)) is None
    assert acceptable_relaxation(PlanRevision(number=3)) is None
