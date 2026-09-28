"""The eval runner (SPEC §12, ADR 0056): play every scenario through the full agent graph and
score each final plan revision.

Each session runs the agent graph in process through the entry points the API's session
service drives it with (`start_planning`, `resume_with_answers`, `resume_with_amendment`,
`graph_state`), on an in-memory checkpointer, with the planning stack the API plans with
(`planning_stack`) but on the eval's own world at the scenario's as-of week. The Context
agent's questions are answered from the scenario when asked, and its amendments are made in
order once a plan waits for approval. The final plan revision is then checked on its plan-time
numbers by `validate_plan` and scored by the oracle on the true demand (ADR 0012).
"""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from langgraph.checkpoint.memory import InMemorySaver

from promopilot.agents import (
    GraphSnapshot,
    GraphTools,
    PlanningGraph,
    PlanningSettings,
    build_graph,
    checkpoint_serializer,
    graph_state,
    planning_stack,
    resume_with_amendment,
    resume_with_answers,
    start_planning,
)
from promopilot.agents.tools.as_of import fixed_as_of_week
from promopilot.domain import (
    Assumption,
    CompanyPolicy,
    DecisionKind,
    OpenIssue,
    PlanDecision,
    PlanExplanation,
    PlanningRequest,
    PlanRevision,
    PromoPlan,
    Violation,
)
from promopilot.evals.metrics import (
    check_constraints,
    check_property,
    constraint_satisfaction,
    oracle_breach_rate,
    oracle_breaches,
)
from promopilot.evals.report import (
    ConstraintCheck,
    EvalReport,
    OracleScore,
    RevisionSummary,
    RunOutcome,
    RunResult,
    ScenarioResult,
)
from promopilot.evals.scenarios import Scenario
from promopilot.evals.world import EvalWorld
from promopilot.llm import LLMProvider

MAX_CLARIFICATION_ROUNDS = 3
"""A session still asking after this many answered rounds is stopped: no final plan."""


async def run(
    scenarios: Sequence[Scenario],
    provider: LLMProvider,
    runs_per_scenario: int = 1,
    *,
    world: EvalWorld,
    settings: PlanningSettings,
    policy: CompanyPolicy | None = None,
    provider_name: str | None = None,
    progress: Callable[[str], None] | None = None,
) -> EvalReport:
    """Play every scenario `runs_per_scenario` times, one session after another, and report.

    Every run of a scenario plans with its seed, so the report is the same for the same world,
    scenarios, settings and LLM answers, apart from its timing (`EvalReport.comparable`). A
    session that fails is reported as failed and the others still run.
    """
    if runs_per_scenario < 1:
        raise ValueError("runs_per_scenario must be at least 1")
    policy = policy or CompanyPolicy()
    results = []
    for scenario in scenarios:
        runs = []
        for number in range(1, runs_per_scenario + 1):
            played = await _run(scenario, number, provider, world, settings, policy)
            runs.append(played)
            if progress is not None:
                progress(
                    f"{scenario.name} run {number}: {played.outcome.value}, constraints "
                    f"{played.constraints.value} ({played.duration_s:.1f}s)"
                )
        results.append(
            ScenarioResult(
                name=scenario.name,
                group=scenario.group.value,
                as_of_week=scenario.as_of_week,
                seed=scenario.seed,
                runs=tuple(runs),
                passed=all(played.passed for played in runs),
            )
        )
    every_run = [played for result in results for played in result.runs]
    return EvalReport(
        generated_at=datetime.now(UTC),
        provider=provider_name or type(provider).__name__,
        world_seed=world.seed,
        runs_per_scenario=runs_per_scenario,
        planning_settings=settings.recorded,
        metrics=(constraint_satisfaction(every_run), oracle_breach_rate(every_run)),
        scenarios=tuple(results),
    )


@dataclass
class _Session:
    """What a session did, as the runner saw it."""

    route: list[str]
    asked: list[str]
    amendments: int = 0
    snapshot: GraphSnapshot | None = None


async def _run(
    scenario: Scenario,
    number: int,
    provider: LLMProvider,
    world: EvalWorld,
    settings: PlanningSettings,
    policy: CompanyPolicy,
) -> RunResult:
    started = time.perf_counter()
    session = _Session(route=[], asked=[])
    try:
        outcome = await _play(scenario, number, provider, world, settings, policy, session)
        result = _score(scenario, number, outcome, session, world, policy)
    except Exception as error:  # a failed session is a result, not the end of the eval
        result = RunResult(
            run=number,
            outcome=RunOutcome.FAILED,
            error=f"{type(error).__name__}: {error}",
            route=tuple(session.route),
            questions_asked=tuple(session.asked),
            amendments_applied=session.amendments,
            properties=tuple(
                check_property(prop, asked=session.asked, revision=None) for prop in scenario.expect
            ),
        )
    return result.model_copy(update={"duration_s": time.perf_counter() - started})


async def _play(
    scenario: Scenario,
    number: int,
    provider: LLMProvider,
    world: EvalWorld,
    settings: PlanningSettings,
    policy: CompanyPolicy,
    session: _Session,
) -> RunOutcome:
    data = world.data(scenario.as_of_week)
    models = await world.models(scenario.as_of_week)
    seeded = settings.seeded(scenario.seed)
    stack = planning_stack(
        models.demand,
        models.relations,
        data,
        policy=policy,
        solver=seeded.solver,
        simulation=seeded.simulation,
        seed=seeded.seed,
        as_of_week=fixed_as_of_week(scenario.as_of_week),
    )
    tools = GraphTools(
        brief_data=data,
        planner=stack.planner,
        sessions=_Unrecorded(),
        policy=policy,
        agent=stack.agent,
        risk_thresholds=seeded.risk_thresholds,
    )
    graph = build_graph(tools, provider, InMemorySaver(serde=checkpoint_serializer()))
    session_id = uuid5(NAMESPACE_URL, f"promopilot:eval:{scenario.name}:{number}")
    thread = str(session_id)
    session.route += await start_planning(graph, thread, session_id, scenario.brief)
    rounds = 0
    while True:
        snapshot = session.snapshot = await _snapshot(graph, thread)
        if snapshot.awaits_clarification:
            asked = [question.id for question in snapshot.values.questions]
            session.asked += asked
            answered = {
                q: scenario.clarifications[q] for q in asked if q in scenario.clarifications
            }
            if rounds >= MAX_CLARIFICATION_ROUNDS or len(answered) < len(asked):
                return RunOutcome.AWAITING_CLARIFICATION
            rounds += 1
            session.route += await resume_with_answers(graph, thread, answered)
        elif snapshot.awaits_decision:
            if session.amendments == len(scenario.amendments):
                return RunOutcome.PLANNED
            amendment = scenario.amendments[session.amendments]
            session.amendments += 1
            session.route += await resume_with_amendment(graph, thread, amendment)
        else:
            raise RuntimeError(f"the session stopped at {snapshot.paused_at or 'its end'}")


async def _snapshot(graph: PlanningGraph, thread: str) -> GraphSnapshot:
    snapshot = await graph_state(graph, thread)
    if snapshot is None:
        raise RuntimeError("the session has no checkpoint")
    return snapshot


def _score(
    scenario: Scenario,
    number: int,
    outcome: RunOutcome,
    session: _Session,
    world: EvalWorld,
    policy: CompanyPolicy,
) -> RunResult:
    state = None if session.snapshot is None else session.snapshot.values
    planned = outcome is RunOutcome.PLANNED and state is not None
    revision = state.plan if planned and state is not None else None
    request = state.plan_request if state is not None else None
    constraints = ConstraintCheck.NO_PLAN
    violations: tuple[Violation, ...] = ()
    oracle: OracleScore | None = None
    summary: RevisionSummary | None = None
    if revision is not None and request is not None and state is not None:
        summary = _summary(revision, request)
        if state.plan_facts is None:
            raise RuntimeError("the final plan revision has no plan facts")
        constraints, violations = check_constraints(
            revision.solver_status, state.plan_facts, request, policy
        )
        if constraints is not ConstraintCheck.INFEASIBLE:
            plan = PromoPlan(lines=tuple(line.line for line in revision.lines))
            true = world.oracle.evaluate(plan, scenario.as_of_week, policy)
            oracle = OracleScore(
                incremental_profit=true.incremental_profit,
                clearance_value=true.clearance_value,
                promo_cost=true.promo_cost,
                blended_margin=true.blended_margin,
                stock_capped_lines=true.stock_capped_lines,
                breaches=oracle_breaches(true, request, policy),
            )
    fallbacks: list[str] = []
    if state is not None:
        if state.context_degraded is not None:
            fallbacks.append(f"context: {state.context_degraded.value}")
        if planned and state.planner_degraded is not None:
            fallbacks.append(f"planner: {state.planner_degraded.value}")
        explained = state.explanations
        if planned and explained is not None and explained.fallback_reason is not None:
            fallbacks.append(f"explainer: {explained.fallback_reason.value}")
    return RunResult(
        run=number,
        outcome=outcome,
        route=tuple(session.route),
        questions_asked=tuple(session.asked),
        amendments_applied=session.amendments,
        fallbacks=tuple(fallbacks),
        revision=summary,
        constraints=constraints,
        violations=violations,
        oracle=oracle,
        properties=tuple(
            check_property(prop, asked=session.asked, revision=revision) for prop in scenario.expect
        ),
    )


def _summary(revision: PlanRevision, request: PlanningRequest) -> RevisionSummary:
    return RevisionSummary(
        number=revision.number,
        lines=len(revision.lines),
        regions=tuple(dict.fromkeys(line.line.region for line in revision.lines)),
        solver_status=revision.solver_status,
        objective=revision.objective,
        promo_cost=sum(line.promo_cost for line in revision.lines),
        marketing_budget=request.marketing_budget,
    )


class _Unrecorded:
    """The session read model, which an eval session does not keep."""

    async def save_assumptions(self, session_id: UUID, assumptions: tuple[Assumption, ...]) -> None:
        return None

    async def save_revision(
        self, session_id: UUID, request: PlanningRequest, revision: PlanRevision
    ) -> None:
        return None

    async def save_open_issues(
        self, session_id: UUID, revision_number: int, issues: tuple[OpenIssue, ...]
    ) -> None:
        return None

    async def save_explanation(
        self, session_id: UUID, revision_number: int, explanation: PlanExplanation
    ) -> None:
        return None

    async def record_decision(
        self, session_id: UUID, decision: DecisionKind, revision_number: int, reason: str | None
    ) -> PlanDecision:
        return PlanDecision(
            decision=decision, revision_number=revision_number, reason=reason, decided_at=FIXED
        )


FIXED = datetime(1970, 1, 1, tzinfo=UTC)
"""An eval session is never decided on; were it, the decision would not depend on the clock."""
