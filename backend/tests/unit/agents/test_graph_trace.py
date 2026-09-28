"""The agent graph's trace (SF-01, #45, ADR 0047): every node's start and end, the Critic's
findings and route, each decision and every billed LLM call, in order."""

from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from promopilot.agents import (
    GraphTools,
    LLMPricing,
    MemoryTrace,
    PlannedRevision,
    PlanningError,
    PlanningGraph,
    build_graph,
    checkpoint_serializer,
    resume_with_decision,
    start_planning,
)
from promopilot.config import ModelPrice
from promopilot.datagen import GeneratedDataset
from promopilot.domain import (
    ClarificationAsked,
    DecisionKind,
    DecisionMade,
    FindingRaised,
    NodeFinished,
    TokensUsed,
    TraceEvent,
)
from promopilot.llm import FakeProvider, LLMError, LLMProvider, Usage
from tests.unit.agents.billed import BilledProvider
from tests.unit.agents.fakes import InMemoryRetailData, explainer_down
from tests.unit.agents.test_graph import (
    BRIEF,
    BUDGET,
    POLICY,
    READING,
    RecordedSessions,
    ScriptedPlanner,
    planned,
)


@pytest.fixture
def data(small_dataset: GeneratedDataset) -> InMemoryRetailData:
    return InMemoryRetailData(small_dataset)


@pytest.fixture
def trace() -> MemoryTrace:
    return MemoryTrace()


def graph_for(
    data: InMemoryRetailData,
    trace: MemoryTrace,
    llm: LLMProvider,
    result: PlannedRevision | None = None,
    pricing: LLMPricing | None = None,
) -> PlanningGraph:
    return build_graph(
        GraphTools(
            brief_data=data,
            planner=ScriptedPlanner(result or planned()),
            sessions=RecordedSessions(),
            policy=POLICY,
            trace=trace,
            pricing=pricing or LLMPricing(),
        ),
        llm,
        InMemorySaver(serde=checkpoint_serializer()),
    )


def steps(events: list[TraceEvent]) -> list[tuple[str | None, str]]:
    """Each event as (node, kind), with a node's end as its outcome."""
    return [
        (
            event.node,
            event.payload.outcome.value
            if isinstance(event.payload, NodeFinished)
            else event.payload.kind,
        )
        for event in events
    ]


async def test_a_planning_run_traces_every_node_in_order_up_to_the_approval_pause(
    data: InMemoryRetailData, trace: MemoryTrace
) -> None:
    graph = graph_for(data, trace, FakeProvider([READING, explainer_down()]))
    session_id = uuid4()

    await start_planning(graph, str(session_id), session_id, BRIEF)

    events = trace.of(session_id)
    assert [event.id for event in events] == list(range(1, len(events) + 1))
    assert steps(events) == [
        ("context", "node_started"),
        ("context", "completed"),
        ("planner", "node_started"),
        ("planner", "completed"),
        ("critic", "node_started"),
        ("critic", "decision"),
        ("critic", "completed"),
        ("explainer", "node_started"),
        ("explainer", "decision"),
        ("explainer", "completed"),
        ("approval", "node_started"),
        ("approval", "interrupted"),
    ]
    decision = events[5].payload
    assert isinstance(decision, DecisionMade)
    assert decision.decision == "plan_valid"


async def test_each_violation_is_a_finding_and_the_critic_decides_to_list_them(
    data: InMemoryRetailData, trace: MemoryTrace
) -> None:
    over_budget = planned(promo_cost=BUDGET + 5_000.0)
    graph = graph_for(data, trace, FakeProvider([READING, explainer_down()]), result=over_budget)
    session_id = uuid4()

    await start_planning(graph, str(session_id), session_id, BRIEF)

    critic = [e.payload for e in trace.of(session_id) if e.node == "critic"]
    findings = [p for p in critic if isinstance(p, FindingRaised)]
    assert [(f.source, f.code) for f in findings] == [("plan_validation", "BUDGET")]
    [decision] = [p for p in critic if isinstance(p, DecisionMade)]
    # The default sequence planned it and would plan it again: no loop-back (ADR 0051).
    assert decision.decision == "default_sequence"


async def test_approving_traces_the_decision_and_the_run_to_done_after_the_pause(
    data: InMemoryRetailData, trace: MemoryTrace
) -> None:
    graph = graph_for(data, trace, FakeProvider([READING, explainer_down()]))
    session_id = uuid4()
    await start_planning(graph, str(session_id), session_id, BRIEF)
    paused = len(trace.of(session_id))

    await resume_with_decision(
        graph,
        str(session_id),
        DecisionKind.APPROVED,
        revision_number=1,
        reason=None,
    )

    events = trace.of(session_id)
    assert [event.id for event in events] == list(range(1, len(events) + 1))
    assert steps(events[paused:]) == [
        ("approval", "node_started"),
        ("approval", "decision"),
        ("approval", "completed"),
        ("done", "node_started"),
        ("done", "completed"),
    ]
    decision = events[paused + 1].payload
    assert isinstance(decision, DecisionMade)
    assert (decision.decision, decision.summary) == (
        "approved",
        "Plan revision 1 was approved.",
    )


async def test_rejecting_traces_the_reason_and_pauses_at_approval_again(
    data: InMemoryRetailData, trace: MemoryTrace
) -> None:
    graph = graph_for(data, trace, FakeProvider([READING, explainer_down()]))
    session_id = uuid4()
    await start_planning(graph, str(session_id), session_id, BRIEF)
    paused = len(trace.of(session_id))

    await resume_with_decision(
        graph,
        str(session_id),
        DecisionKind.REJECTED,
        revision_number=1,
        reason="Too deep in West",
    )

    after = trace.of(session_id)[paused:]
    assert steps(after) == [
        ("approval", "node_started"),
        ("approval", "decision"),
        ("approval", "completed"),
        ("approval", "node_started"),
        ("approval", "interrupted"),
    ]
    decision = after[1].payload
    assert isinstance(decision, DecisionMade)
    assert (decision.decision, decision.summary) == (
        "rejected",
        "Plan revision 1 was rejected: Too deep in West",
    )


class CrashingPlanner:
    async def plan(self, request: object) -> PlannedRevision:
        raise PlanningError("the solver crashed")


async def test_a_failing_node_is_traced_as_failed(
    data: InMemoryRetailData, trace: MemoryTrace
) -> None:
    graph = build_graph(
        GraphTools(
            brief_data=data,
            planner=CrashingPlanner(),
            sessions=RecordedSessions(),
            policy=POLICY,
            trace=trace,
        ),
        FakeProvider([READING]),
        InMemorySaver(serde=checkpoint_serializer()),
    )
    session_id = uuid4()

    with pytest.raises(PlanningError, match="the solver crashed"):
        await start_planning(graph, str(session_id), session_id, BRIEF)

    assert steps(trace.of(session_id)) == [
        ("context", "node_started"),
        ("context", "completed"),
        ("planner", "node_started"),
        ("planner", "failed"),
    ]


async def test_the_llm_down_at_context_is_a_fallback_decision_not_a_failure(
    data: InMemoryRetailData, trace: MemoryTrace
) -> None:
    graph = graph_for(data, trace, FakeProvider([LLMError("provider down"), explainer_down()]))
    session_id = uuid4()

    await start_planning(graph, str(session_id), session_id, BRIEF)

    events = trace.of(session_id)
    assert steps(events)[:3] == [
        ("context", "node_started"),
        ("context", "decision"),
        ("context", "completed"),
    ]
    decision = events[1].payload
    assert isinstance(decision, DecisionMade)
    assert decision.decision == "context_fallback"
    assert "llm_unavailable" in decision.summary
    assert steps(events)[-1] == ("approval", "interrupted")


async def test_a_question_is_a_clarification_event_and_clarify_pauses(
    data: InMemoryRetailData, trace: MemoryTrace
) -> None:
    unbudgeted = READING.model_copy(update={"marketing_budget": None})
    graph = graph_for(data, trace, FakeProvider([unbudgeted]))
    session_id = uuid4()

    await start_planning(graph, str(session_id), session_id, BRIEF)

    events = trace.of(session_id)
    assert steps(events) == [
        ("context", "node_started"),
        ("context", "clarification"),
        ("context", "completed"),
        ("clarify", "node_started"),
        ("clarify", "interrupted"),
    ]
    [asked] = [e.payload for e in events if isinstance(e.payload, ClarificationAsked)]
    assert len(asked.questions) == 1
    assert "budget" in asked.questions[0]


async def test_the_context_agents_llm_call_is_a_priced_token_usage_event(
    data: InMemoryRetailData, trace: MemoryTrace
) -> None:
    llm = BilledProvider(
        FakeProvider([READING, explainer_down()]),
        [
            Usage(model="gpt-4.1-mini", input_tokens=1_200, output_tokens=300),
            Usage(model="gpt-4.1-mini", input_tokens=900, output_tokens=0),
        ],
    )
    pricing = LLMPricing(
        prices={"gpt-4.1-mini": ModelPrice(input_usd_per_mtok=0.40, output_usd_per_mtok=1.60)},
        usd_inr_rate=96.0,
    )
    graph = graph_for(data, trace, llm, pricing=pricing)
    session_id: UUID = uuid4()

    await start_planning(graph, str(session_id), session_id, BRIEF)

    usage, explaining = [e for e in trace.of(session_id) if isinstance(e.payload, TokensUsed)]
    # The Explainer's call fails, but it was billed, so it counts too.
    assert explaining.node == "explainer"
    assert usage.node == "context"
    assert isinstance(usage.payload, TokensUsed)
    # 1200 x $0.40/M + 300 x $1.60/M = $0.00096
    assert usage.payload.cost_usd == pytest.approx(0.00096)
    assert usage.payload.cost_inr == pytest.approx(0.00096 * 96)
    assert steps(trace.of(session_id))[:3] == [
        ("context", "node_started"),
        ("context", "token_usage"),
        ("context", "completed"),
    ]
