"""The Critic loop (AG-04, AG-06, #48, ADR 0051), driven with a FakeProvider: violations and
risk findings go back to the planner agent with feedback, at most 3 times, and the best plan
goes on to the Explainer with its open issues listed."""

import json
from collections.abc import Sequence
from typing import Any
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel

from promopilot.agents import (
    AgentTools,
    CriticFeedback,
    FindingFeedback,
    GraphTools,
    PlannedRevision,
    Planner,
    StoredRevisions,
    build_graph,
    checkpoint_serializer,
    graph_state,
    read_planning_request,
    start_planning,
)
from promopilot.agents.state import PlanningState
from promopilot.agents.tools import ToolOk, ToolRegistry
from promopilot.agents.tools.as_of import fixed_as_of_week
from promopilot.agents.tools.generate_candidates import (
    GenerateCandidatesOutput,
    generate_candidates_tool,
)
from promopilot.agents.tools.get_competitor_gaps import get_competitor_gaps_tool
from promopilot.agents.tools.inventory_status import pooled_stock
from promopilot.agents.tools.run_optimizer import run_optimizer_tool
from promopilot.agents.trace import MemoryTrace
from promopilot.datagen import GeneratedDataset
from promopilot.domain import (
    BindingConstraint,
    BindingEvidence,
    ConstraintKind,
    ConstraintSource,
    DecisionMade,
    FindingRaised,
    PlanningRequest,
    PlanRevision,
    PlanSimulation,
    Relaxation,
    RelaxedConstraint,
    RiskCode,
    RiskFinding,
    SimulatedOutcomes,
    SolveStatus,
    Violation,
    ViolationCode,
)
from promopilot.guardrails import RiskThresholds, check_numeric_grounding
from promopilot.llm import FakeProvider, LLMError
from promopilot.models.demand import DemandModel
from promopilot.models.registry import ModelKind
from promopilot.models.relations import Relations
from promopilot.optimizer import CandidateStore, SolverSettings
from tests.unit.agents.fakes import InMemoryRetailData, explainer_down
from tests.unit.agents.test_generate_candidates import Fixed, entry
from tests.unit.agents.test_graph import BRIEF, BUDGET, POLICY, READING, ScriptedPlanner, planned
from tests.unit.agents.test_plan_session import FREE, planner_of
from tests.unit.agents.test_planner_agent import (
    Generated,
    Revisions,
    ScriptedTools,
    Sleeps,
    call,
    finish,
    generate,
    optimised,
    run,
)

HISTORY_WEEKS = 52  # small_config
ONE_PASS = ["context", "planner", "critic", "explainer", "approval"]


def loops(count: int) -> list[str]:
    """The route with `count` loop-backs from the Critic to the Planner."""
    return ["context", *(["planner", "critic"] * (count + 1)), "explainer", "approval"]


def set_id(attempt: int) -> UUID:
    return UUID(int=attempt)


class Saved:
    """What the graph records for its sessions, keeping every revision it saves."""

    def __init__(self) -> None:
        self.revisions: list[PlanRevision] = []
        self.open_issues: list[tuple[int, tuple[Violation | RiskFinding, ...]]] = []

    async def save_revision(
        self, session_id: UUID, request: PlanningRequest, revision: PlanRevision
    ) -> None:
        self.revisions.append(revision)

    async def save_open_issues(
        self, session_id: UUID, revision_number: int, issues: tuple[Violation | RiskFinding, ...]
    ) -> None:
        self.open_issues.append((revision_number, issues))

    async def save_explanation(self, *args: object) -> None:
        return None

    async def save_assumptions(self, *args: object) -> None:
        return None

    async def record_decision(self, *args: object) -> Any:
        raise AssertionError("no decision in these tests")


def plan(
    *,
    promo_cost: float = 1_500.0,
    p90_units: float = 450.0,
    objective: float = 6_250.0,
    stockout_probability: float | None = None,
    relaxation: Relaxation | None = None,
) -> PlannedRevision:
    """A one-line plan revision: a promo cost above the budget or P90 units above the stock
    break it; a stock-out probability simulates it."""
    base = planned(promo_cost=promo_cost)
    simulation = None
    if stockout_probability is not None:
        simulation = PlanSimulation(
            n_runs=200,
            seed=5,
            lines=(
                {
                    "sku_id": "SKU0001",
                    "region": "North",
                    "stockout_probability": stockout_probability,
                    **outcomes(),
                },
            ),
            total=SimulatedOutcomes(**outcomes()),
        )
    revision = base.revision.model_copy(
        update={"objective": objective, "simulation": simulation, "relaxation": relaxation}
        | (
            {
                "solver_status": SolveStatus.INFEASIBLE,
                "binding_constraints": (
                    BindingConstraint(
                        kind=ConstraintKind.CLEARANCE_TARGET,
                        source=ConstraintSource.BRIEF,
                        limit=1.0,
                        region="North",
                        sku_id="SKU0001",
                        evidence=BindingEvidence.INFEASIBLE,
                        objective_gain=None,
                    ),
                ),
            }
            if relaxation is not None
            else {}
        )
    )
    [line] = base.facts.lines
    facts = base.facts.model_copy(
        update={"lines": (line.model_copy(update={"p90_units": p90_units}),)}
    )
    return PlannedRevision(revision, facts)


def outcomes() -> dict[str, Any]:
    ranged = {"p10": 1.0, "p50": 1.0, "p90": 1.0}
    return {
        "units": ranged,
        "revenue": ranged,
        "gross_profit": ranged,
        "margin": ranged,
        "promo_spend": ranged,
        "sell_through": None,
    }


def attempt_turns(request: PlanningRequest) -> list[BaseModel]:
    """One planner attempt: generate candidates, optimise, stop."""
    return [generate(request), run(), finish()]


@pytest.fixture
def data(small_dataset: GeneratedDataset) -> InMemoryRetailData:
    return InMemoryRetailData(small_dataset)


@pytest.fixture
async def request_read(data: InMemoryRetailData) -> PlanningRequest:
    return await read_planning_request(BRIEF, FakeProvider([READING]), data)


class Run:
    def __init__(self, route: list[str], state: PlanningState, llm: FakeProvider, saved: Saved):
        self.route = route
        self.state = state
        self.llm = llm
        self.saved = saved

    def planner_openings(self) -> list[str]:
        """The user messages each planner conversation opened with."""
        return [
            "\n".join(m.content for m in call.messages if m.role == "user")
            for call in self.llm.calls
            if call.schema is None and all(m.role in ("system", "user") for m in call.messages)
        ]


async def run_graph(
    data: InMemoryRetailData,
    script: Sequence[BaseModel | Exception],
    *,
    attempts: Sequence[PlannedRevision] = (),
    default: Planner | None = None,
    agent: bool = True,
    risk_thresholds: RiskThresholds | None = None,
    trace: MemoryTrace | None = None,
) -> Run:
    """Plan BRIEF with the planner agent, whose attempt k ends with the k-th plan."""
    tools = ScriptedTools(
        {
            "generate_candidates": [
                Generated(candidate_set_id=set_id(k)) for k in range(1, len(attempts) + 1)
            ]
            or [Generated(candidate_set_id=set_id(1))],
            "run_optimizer": [optimised(set_id(k)) for k in range(1, len(attempts) + 1)]
            or [optimised(set_id(1))],
        }
    )
    llm = FakeProvider([READING, *script, explainer_down()])
    saved = Saved()
    graph_tools = GraphTools(
        brief_data=data,
        planner=default or ScriptedPlanner(planned()),
        sessions=saved,
        policy=POLICY,
        agent=AgentTools(
            tools=tools,
            revisions=Revisions({set_id(k): p for k, p in enumerate(attempts, start=1)}),
            sleep=Sleeps(),
        )
        if agent
        else None,
        risk_thresholds=risk_thresholds or RiskThresholds(),
        trace=trace or MemoryTrace(),
    )
    graph = build_graph(graph_tools, llm, InMemorySaver(serde=checkpoint_serializer()))
    session_id = uuid4()
    route = await start_planning(graph, str(session_id), session_id, BRIEF)
    snapshot = await graph_state(graph, str(session_id))
    assert snapshot is not None
    return Run(route, snapshot.values, llm, saved)


def over_budget(by: float, **changes: Any) -> PlannedRevision:
    return plan(promo_cost=BUDGET + by, **changes)


# The loop and its cap.


async def test_violations_loop_to_the_planner_at_most_3_times_then_go_to_the_explainer(
    data: InMemoryRetailData, request_read: PlanningRequest
) -> None:
    attempts = [over_budget(by) for by in (4_000.0, 3_000.0, 2_000.0, 1_000.0)]

    run = await run_graph(data, _turns(request_read, 4), attempts=attempts)

    assert run.route == loops(3)
    assert run.state.iteration == 4
    assert len(run.state.attempts) == 4
    # Every attempt breaks the budget: the tie goes to the latest, with its open issues.
    [violation] = run.state.critic_findings
    assert violation.code is ViolationCode.BUDGET
    assert run.state.plan == attempts[3].revision
    assert run.saved.revisions == [attempts[3].revision]
    assert run.saved.open_issues == [(1, (violation,))]
    assert run.state.explanations is not None
    assert "BUDGET" in run.state.explanations.summary


def _turns(request: PlanningRequest, count: int) -> list[BaseModel]:
    return [turn for _ in range(count) for turn in attempt_turns(request)]


async def test_the_planner_is_given_the_critics_findings_as_feedback(
    data: InMemoryRetailData, request_read: PlanningRequest
) -> None:
    attempts = [over_budget(5_000.0), plan()]

    run = await run_graph(data, _turns(request_read, 2), attempts=attempts)

    assert run.route == loops(1)
    first, second = run.planner_openings()
    assert "Critic" not in first
    assert "Critic" in second
    assert "BUDGET" in second
    assert "exceeds the marketing budget" in second


async def test_the_feedback_shows_each_finding_as_worded_not_its_raw_numbers(
    data: InMemoryRetailData, request_read: PlanningRequest
) -> None:
    # A raw float (0.5183146894877728) differs in its last digits between machines, so a
    # recorded loop-back would not replay on another (ADR 0054); the message states the
    # numbers as the finding shows them.
    run = await run_graph(data, _turns(request_read, 2), attempts=[over_budget(5_000.0), plan()])

    _, second = run.planner_openings()
    findings = json.loads(second.split("constraints stay as given:\n", 1)[1])
    assert findings
    assert all("actual" not in finding and "limit" not in finding for finding in findings)
    assert all(finding["message"] for finding in findings)


async def test_a_plan_that_passes_after_a_loop_is_the_one_saved_with_no_open_issues(
    data: InMemoryRetailData, request_read: PlanningRequest
) -> None:
    attempts = [over_budget(5_000.0), plan(objective=5_000.0)]

    run = await run_graph(data, _turns(request_read, 2), attempts=attempts)

    assert run.route == loops(1)
    assert run.state.critic_findings == ()
    assert run.saved.revisions == [attempts[1].revision]
    assert run.saved.open_issues == [(1, ())]


async def test_the_best_attempt_has_fewest_violations_then_findings_then_highest_objective(
    data: InMemoryRetailData, request_read: PlanningRequest
) -> None:
    attempts = [
        over_budget(1_000.0, p90_units=5_000.0),  # 2 violations
        over_budget(2_000.0, objective=5_000.0),  # 1 violation
        over_budget(1_000.0, objective=7_000.0),  # 1 violation, the highest objective
        over_budget(1_000.0, objective=6_000.0, stockout_probability=0.5),  # 1 + a risk
    ]
    critic = CriticFeedback(
        feedback=[FindingFeedback(finding=1, feedback="Promote SKU0001 less deeply.")]
    )
    script = [*_turns(request_read, 3), *attempt_turns(request_read), critic]

    run = await run_graph(data, script, attempts=attempts)

    assert run.route == loops(3)
    assert run.state.plan == attempts[2].revision
    assert run.saved.revisions == [attempts[2].revision]
    [(_, issues)] = run.saved.open_issues
    assert [issue.code for issue in issues] == [ViolationCode.BUDGET]


# Risk findings.


async def test_risk_findings_loop_with_the_llms_grounded_feedback(
    data: InMemoryRetailData, request_read: PlanningRequest
) -> None:
    attempts = [plan(stockout_probability=0.45), plan(stockout_probability=0.05)]
    worded = "SKU0001 runs out in 45% of runs: promote it for one week instead of two."
    critic = CriticFeedback(feedback=[FindingFeedback(finding=1, feedback=worded)])
    script = [*attempt_turns(request_read), critic, *attempt_turns(request_read)]

    run = await run_graph(data, script, attempts=attempts)

    assert run.route == loops(1)
    [reviewed, passed] = run.state.attempts
    [finding] = reviewed.findings
    assert isinstance(finding, RiskFinding)
    assert finding.code is RiskCode.STOCKOUT_RISK
    assert finding.feedback == worded
    assert passed.findings == ()
    _, second = run.planner_openings()
    assert worded in second
    assert "STOCKOUT_RISK" in second
    # The Critic's LLM was shown the findings only, and never asked for a number.
    [critic_call] = [call for call in run.llm.calls if call.schema is CriticFeedback]
    assert "45%" in critic_call.messages[1].content


@pytest.mark.parametrize(
    "answer",
    [
        CriticFeedback(
            feedback=[FindingFeedback(finding=1, feedback="It runs out in 62% of runs.")]
        ),
        CriticFeedback(feedback=[]),
        CriticFeedback(feedback=[FindingFeedback(finding=1, feedback="  ")]),
        LLMError("the Critic's LLM is down"),
    ],
    ids=["ungrounded", "missing", "blank", "llm_down"],
)
async def test_feedback_the_llm_cannot_word_falls_back_to_the_template(
    data: InMemoryRetailData, request_read: PlanningRequest, answer: BaseModel | Exception
) -> None:
    attempts = [plan(stockout_probability=0.45), plan()]
    script = [*attempt_turns(request_read), answer, *attempt_turns(request_read)]

    run = await run_graph(data, script, attempts=attempts)

    assert run.route == loops(1)
    [finding] = run.state.attempts[0].findings
    assert isinstance(finding, RiskFinding)
    assert finding.feedback.startswith("Leave SKU0001 out with generate_candidates'")
    assert check_numeric_grounding(finding.feedback, finding.message).grounded


async def test_risk_findings_left_at_the_cap_are_open_issues_on_the_revision(
    data: InMemoryRetailData, request_read: PlanningRequest
) -> None:
    # Each attempt runs out less often, but never below the threshold.
    attempts = [plan(stockout_probability=p) for p in (0.45, 0.40, 0.35, 0.30)]
    llm_down: BaseModel | Exception = LLMError("the Critic's LLM is down")
    script = [turn for _ in range(4) for turn in (*attempt_turns(request_read), llm_down)]
    trace = MemoryTrace()

    run = await run_graph(data, script, attempts=attempts, trace=trace)

    assert run.route == loops(3)
    [(_, [issue])] = run.saved.open_issues
    assert isinstance(issue, RiskFinding)
    assert issue.code is RiskCode.STOCKOUT_RISK
    assert "30%" in issue.message
    assert critic_decisions(trace)[-1] == "cap_reached"


def critic_decisions(trace: MemoryTrace) -> list[str]:
    return [
        event.payload.decision
        for event in trace.events
        if event.node == "critic" and isinstance(event.payload, DecisionMade)
    ]


# Findings that repeat end the loop early (ADR 0059).


async def test_findings_repeated_exactly_end_the_loop_early_with_open_issues_listed(
    data: InMemoryRetailData, request_read: PlanningRequest
) -> None:
    # The next attempt would open with the same findings, so it would plan the same again.
    attempts = [plan(stockout_probability=0.45)] * 4
    llm_down: BaseModel | Exception = LLMError("the Critic's LLM is down")
    script = [turn for _ in range(2) for turn in (*attempt_turns(request_read), llm_down)]
    trace = MemoryTrace()

    run = await run_graph(data, script, attempts=attempts, trace=trace)

    assert run.route == loops(1)
    assert len(run.state.attempts) == 2
    [(_, [issue])] = run.saved.open_issues
    assert isinstance(issue, RiskFinding)
    assert issue.code is RiskCode.STOCKOUT_RISK
    assert run.state.critic_findings == (issue,)
    assert critic_decisions(trace) == ["loop_back", "findings_repeated"]
    [handed_on] = [
        event.payload.summary
        for event in trace.events
        if isinstance(event.payload, DecisionMade) and event.payload.decision == "findings_repeated"
    ]
    assert "same findings as attempt 1" in handed_on
    assert "Attempt 2 of 2 is the best plan" in handed_on


async def test_findings_repeated_in_other_words_still_end_the_loop_early(
    data: InMemoryRetailData, request_read: PlanningRequest
) -> None:
    # Only the Critic's LLM wording differs: the planner has the same findings to address.
    attempts = [plan(stockout_probability=0.45)] * 4
    worded = CriticFeedback(
        feedback=[FindingFeedback(finding=1, feedback="Promote SKU0001 for one week only.")]
    )
    llm_down: BaseModel | Exception = LLMError("the Critic's LLM is down")
    script = [*attempt_turns(request_read), worded, *attempt_turns(request_read), llm_down]

    run = await run_graph(data, script, attempts=attempts)

    assert run.route == loops(1)
    first, second = (attempt.findings for attempt in run.state.attempts)
    assert first != second


async def test_findings_that_change_keep_the_loop_going(
    data: InMemoryRetailData, request_read: PlanningRequest
) -> None:
    # Same finding, other numbers: the planner moved, so it has another try.
    attempts = [plan(stockout_probability=0.45), plan(stockout_probability=0.40), plan()]
    llm_down: BaseModel | Exception = LLMError("the Critic's LLM is down")
    script = [turn for _ in range(2) for turn in (*attempt_turns(request_read), llm_down)]
    script += attempt_turns(request_read)

    run = await run_graph(data, script, attempts=attempts)

    assert run.route == loops(2)
    assert run.state.critic_findings == ()


async def test_findings_and_the_critics_decisions_are_trace_events(
    data: InMemoryRetailData, request_read: PlanningRequest
) -> None:
    attempts = [over_budget(5_000.0, stockout_probability=0.45), plan(objective=5_000.0)]
    llm_down: BaseModel | Exception = LLMError("the Critic's LLM is down")
    script = [*attempt_turns(request_read), llm_down, *attempt_turns(request_read)]
    trace = MemoryTrace()

    run = await run_graph(data, script, attempts=attempts, trace=trace)

    assert run.route == loops(1)
    critic = [event.payload for event in trace.events if event.node == "critic"]
    findings = [p for p in critic if isinstance(p, FindingRaised)]
    assert [(f.source, f.code) for f in findings] == [
        ("plan_validation", "BUDGET"),
        ("risk_review", "STOCKOUT_RISK"),
    ]
    assert "runs out of stock in 45%" in findings[1].message
    decisions = [p for p in critic if isinstance(p, DecisionMade)]
    assert [d.decision for d in decisions] == ["loop_back", "plan_valid"]
    assert "attempt 1 of 4 back to the planner with 2 findings" in decisions[0].summary
    assert "Attempt 2 of 2 is the best plan" in decisions[1].summary


# When the Critic does not loop.


async def test_the_default_sequence_is_not_looped_as_it_would_plan_the_same_revision(
    data: InMemoryRetailData,
) -> None:
    run = await run_graph(data, [], default=ScriptedPlanner(over_budget(5_000.0)), agent=False)

    assert run.route == ONE_PASS
    [violation] = run.state.critic_findings
    assert violation.code is ViolationCode.BUDGET
    assert run.saved.open_issues == [(1, (violation,))]


async def test_a_degraded_planner_is_not_looped(data: InMemoryRetailData) -> None:
    llm_down = LLMError("the planner's LLM is down")

    run = await run_graph(data, [llm_down], default=ScriptedPlanner(over_budget(5_000.0)))

    assert run.route == ONE_PASS
    assert run.state.planner_degraded is not None
    assert [issue.code for issue in run.state.critic_findings] == [ViolationCode.BUDGET]


async def test_a_plan_with_findings_below_the_thresholds_goes_straight_on(
    data: InMemoryRetailData, request_read: PlanningRequest
) -> None:
    run = await run_graph(
        data, attempt_turns(request_read), attempts=[plan(stockout_probability=0.19)]
    )

    assert run.route == ONE_PASS
    assert run.state.critic_findings == ()


# Infeasible requests (AG-06).

RELAXATION = Relaxation(
    changes=(
        RelaxedConstraint(
            kind=ConstraintKind.CLEARANCE_TARGET,
            sku_id="SKU0001",
            current=1.0,
            relaxed=0.6,
            change=0.4,
        ),
    ),
    policy_binds=True,
    proven=True,
)


async def test_an_infeasible_plan_of_the_agent_goes_on_with_its_relaxation_without_a_loop(
    data: InMemoryRetailData, request_read: PlanningRequest
) -> None:
    infeasible = plan(relaxation=RELAXATION, stockout_probability=0.45)
    llm_down = LLMError("the Critic's LLM is down")

    run = await run_graph(data, [*attempt_turns(request_read), llm_down], attempts=[infeasible])

    # Only an amended brief can fix it: planning again would find the same relaxation.
    assert run.route == ONE_PASS
    [saved] = run.saved.revisions
    assert saved.relaxation == RELAXATION
    assert [b.kind for b in saved.binding_constraints] == [ConstraintKind.CLEARANCE_TARGET]
    assert [issue.code for issue in run.state.critic_findings] == [RiskCode.STOCKOUT_RISK]
    explanation = run.state.explanations
    assert explanation is not None
    assert "Binding constraints: the clearance target for SKU0001 in North" in explanation.summary
    assert "The smallest relaxation: the clearance target for SKU0001" in explanation.summary


class WithUnreachableClearance:
    """The default sequence planning the brief with a clearance target no plan reaches, as a
    brief naming one would ask (the Context agent reads clearance targets from #46 on)."""

    def __init__(self, inner: Planner, sku_id: str) -> None:
        self._inner = inner
        self._sku_id = sku_id

    async def plan(self, request: PlanningRequest) -> PlannedRevision:
        target = {"sku_id": self._sku_id, "sell_through": 1.0}
        return await self._inner.plan(
            PlanningRequest.model_validate(request.model_dump() | {"clearance_targets": [target]})
        )


async def test_an_infeasible_request_on_the_default_sequence_names_its_relaxation_and_binding(
    data: InMemoryRetailData,
    small_models: tuple[DemandModel, Relations],
    small_dataset: GeneratedDataset,
) -> None:
    # Selling all of the Snacks SKU with the most cover in two weeks is out of reach.
    snapshot = small_dataset.inventory.query(f"snapshot_week == {HISTORY_WEEKS - 1}")
    pooled = pooled_stock(snapshot, small_dataset.stores, FREE)
    snacks = set(small_dataset.products.query("category == 'Snacks'")["sku_id"])
    covered = pooled[pooled["sku_id"].isin(snacks)].sort_values("days_of_cover")
    sku_id = str(covered["sku_id"].iloc[-1])
    planner = WithUnreachableClearance(planner_of(small_models, data, FREE), sku_id)

    # The risks of this small plan are not under test here.
    no_risk = RiskThresholds(
        line_spend_share=1.0,
        group_spend_share=1.0,
        cannibalisation_share=100.0,
        stockout_probability=1.0,
    )
    run = await run_graph(data, [], default=planner, agent=False, risk_thresholds=no_risk)

    assert run.route == ONE_PASS
    [saved] = run.saved.revisions
    assert saved.solver_status is SolveStatus.INFEASIBLE
    assert saved.relaxation is not None
    assert [change.sku_id for change in saved.relaxation.changes] == [sku_id]
    assert {(b.kind, b.sku_id) for b in saved.binding_constraints} == {
        (ConstraintKind.CLEARANCE_TARGET, sku_id)
    }
    explanation = run.state.explanations
    assert explanation is not None
    assert f"the clearance target for {sku_id}" in explanation.summary
    assert "The smallest relaxation" in explanation.summary


# Thresholds.


async def test_the_risk_thresholds_come_from_the_graph_tools(
    data: InMemoryRetailData, request_read: PlanningRequest
) -> None:
    llm = FakeProvider([READING, *attempt_turns(request_read), explainer_down()])
    saved = Saved()
    graph = build_graph(
        GraphTools(
            brief_data=data,
            planner=ScriptedPlanner(planned()),
            sessions=saved,
            policy=POLICY,
            agent=AgentTools(
                tools=ScriptedTools(
                    {
                        "generate_candidates": [Generated(candidate_set_id=set_id(1))],
                        "run_optimizer": [optimised(set_id(1))],
                    }
                ),
                revisions=Revisions({set_id(1): plan(stockout_probability=0.45)}),
                sleep=Sleeps(),
            ),
            risk_thresholds=RiskThresholds(stockout_probability=0.5),
        ),
        llm,
        InMemorySaver(serde=checkpoint_serializer()),
    )
    session_id = uuid4()

    assert await start_planning(graph, str(session_id), session_id, BRIEF) == ONE_PASS
    assert saved.open_issues == [(1, ())]


def test_the_critic_prompt_is_versioned() -> None:
    from promopilot.agents.critic import critic_prompt

    assert critic_prompt().startswith("<!-- prompt: critic v2")


# The planner acts on a finding with the tools (ADR 0059).


async def test_a_finding_goes_away_when_the_next_attempt_leaves_its_sku_out(
    data: InMemoryRetailData,
    small_models: tuple[DemandModel, Relations],
    request_read: PlanningRequest,
) -> None:
    # On the small world, SKU0004's substitutes lose 24% of its incremental profit: heavy
    # at a 20% limit. The tools compute every number; the LLM only chooses the calls.
    store = CandidateStore()
    demand = Fixed((entry(ModelKind.DEMAND, 1), small_models[0]))
    relations = Fixed((entry(ModelKind.RELATIONS, 1), small_models[1]))
    week = fixed_as_of_week(HISTORY_WEEKS)
    registry = ToolRegistry(
        [
            get_competitor_gaps_tool(data, week, policy=FREE),
            generate_candidates_tool(demand, relations, data, week, policy=FREE, store=store),
            run_optimizer_tool(store, policy=FREE, settings=SolverSettings(), seed=0),
        ]
    )

    async def preview(**changes: Any) -> UUID:
        arguments = {"request": request_read.model_dump(mode="json"), **changes}
        result = await registry.call("generate_candidates", arguments)
        assert isinstance(result, ToolOk), result
        assert isinstance(result.output, GenerateCandidatesOutput)
        return result.output.candidate_set_id

    first, second = await preview(), await preview(exclude_sku_ids=["SKU0004"])
    llm_down: BaseModel | Exception = LLMError("the Critic's LLM is down")
    llm = FakeProvider(
        [
            READING,
            generate(request_read),
            call("run_optimizer", candidate_set_id=str(first)),
            finish(),
            llm_down,
            generate(request_read, exclude_sku_ids=["SKU0004"]),
            call("run_optimizer", candidate_set_id=str(second)),
            finish(),
            explainer_down(),
        ]
    )
    graph_tools = GraphTools(
        brief_data=data,
        planner=planner_of(small_models, data),
        sessions=Saved(),
        policy=FREE,
        agent=AgentTools(
            tools=registry,
            revisions=StoredRevisions(store, planner_of(small_models, data)),
            sleep=Sleeps(),
        ),
        risk_thresholds=RiskThresholds(line_spend_share=1.0, cannibalisation_share=0.2),
        trace=MemoryTrace(),
    )
    graph = build_graph(graph_tools, llm, InMemorySaver(serde=checkpoint_serializer()))
    session_id = uuid4()

    route = await start_planning(graph, str(session_id), session_id, BRIEF)

    assert route == loops(1)
    snapshot = await graph_state(graph, str(session_id))
    assert snapshot is not None
    flagged, fixed = snapshot.values.attempts
    [finding] = flagged.findings
    assert isinstance(finding, RiskFinding)
    assert (finding.code, finding.sku_id) == (RiskCode.HEAVY_CANNIBALISATION, "SKU0004")
    assert "exclude_sku_ids" in finding.feedback
    assert fixed.findings == ()
    assert "SKU0004" in {line.line.sku_id for line in flagged.plan.lines}
    assert "SKU0004" not in {line.line.sku_id for line in fixed.plan.lines}
    assert snapshot.values.plan == fixed.plan
