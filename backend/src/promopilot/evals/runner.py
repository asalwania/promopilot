"""The eval runner (SPEC §12, ADR 0056): play every scenario through the full agent graph and
score each final plan revision.

Each session runs the agent graph in process through the entry points the API's session
service drives it with (`start_planning`, `resume_with_answers`, `resume_with_amendment`,
`resume_with_acceptance`, `graph_state`), on an in-memory checkpointer, with the planning stack
the API plans with (`planning_stack`) but on the eval's own world at the scenario's as-of week.
The Context agent's questions are answered from the scenario when asked, and its amendments are
made in order once a plan waits for approval. An amendment that accepts the waiting revision's
relaxation accepts it as `POST /amend {accept_relaxation: true}` does, and fails the run when
the revision has no relaxation to accept (ADR 0076, ADR 0083). The final plan
revision is then checked on its plan-time numbers by `validate_plan` and scored by the oracle
on the true demand (ADR 0012).

The session's trace is kept in memory: its token-usage events give the session's cost, and
the agent's behaviour is scored from its outcome (#55, ADR 0062): the final request against
the scenario's labels, what it asked and flagged, how it handled an infeasible request, each
Explainer run, and its time without fitting models.

A scored plan is also compared with the rule-based baseline and the best plan for its
final request (ADR 0063).
"""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel

from promopilot.agents import (
    GraphSnapshot,
    GraphTools,
    LLMPricing,
    MemoryTrace,
    PlanningGraph,
    PlanningSettings,
    acceptable_relaxation,
    build_graph,
    checkpoint_serializer,
    graph_state,
    planning_stack,
    resume_with_acceptance,
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
    Relaxation,
    Violation,
)
from promopilot.evals.behaviour import (
    behaviour_metrics,
    check_clarification,
    check_infeasibility,
    explainer_run,
    kvi_response,
    match_fields,
    session_usage,
    unneeded_asks,
)
from promopilot.evals.cassettes import MissLog
from promopilot.evals.metrics import (
    check_constraints,
    check_property,
    constraint_satisfaction,
    open_issues,
    oracle_breach_rate,
    oracle_breaches,
)
from promopilot.evals.quality import (
    Benchmarks,
    consistency,
    plan_quality,
    regret_metric,
    scenario_consistency,
)
from promopilot.evals.recovery import recovery_metrics
from promopilot.evals.report import (
    ConstraintCheck,
    EvalReport,
    ExplainerRun,
    OracleScore,
    RevisionSummary,
    RunOutcome,
    RunResult,
    ScenarioResult,
)
from promopilot.evals.scenarios import KviResponsePresent, NoStrongSubstitutesTogether, Scenario
from promopilot.evals.substitutes import SubstitutePair, strong_in_scope, strong_substitutes
from promopilot.evals.world import EvalWorld
from promopilot.llm import LLMProvider, Message, ToolSpec, ToolTurn

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
    pricing: LLMPricing | None = None,
    provider_name: str | None = None,
    progress: Callable[[str], None] | None = None,
) -> EvalReport:
    """Play every scenario `runs_per_scenario` times, one session after another, and report.

    Every run of a scenario plans with its seed, so the report is the same for the same world,
    scenarios, settings and LLM answers, apart from its timing (`EvalReport.comparable`). A
    session that fails is reported as failed and the others still run. Token usage is costed
    with `pricing` (the app's `LLM_PRICES`); without it every model is unpriced.
    """
    if runs_per_scenario < 1:
        raise ValueError("runs_per_scenario must be at least 1")
    policy = policy or CompanyPolicy()
    pricing = pricing or LLMPricing()
    benchmarks = Benchmarks(world, settings, policy)
    results = []
    for scenario in scenarios:
        runs = []
        for number in range(1, runs_per_scenario + 1):
            played = await _run(
                scenario, number, provider, world, settings, policy, pricing, benchmarks
            )
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
                consistency=scenario_consistency(runs),
            )
        )
    every_run = [played for result in results for played in result.runs]
    # Once per report, on the models as of the world's default week (ADR 0064).
    recovery = await recovery_metrics(world)
    return EvalReport(
        generated_at=datetime.now(UTC),
        provider=provider_name or type(provider).__name__,
        world_seed=world.seed,
        runs_per_scenario=runs_per_scenario,
        planning_settings=settings.recorded,
        metrics=(
            constraint_satisfaction(every_run),
            oracle_breach_rate(every_run),
            open_issues(every_run),
            *behaviour_metrics(every_run),
            *recovery,
            plan_quality(results),
            regret_metric(every_run),
            consistency(results),
        ),
        scenarios=tuple(results),
    )


@dataclass
class _Session:
    """What a session did, as the runner saw it."""

    route: list[str]
    asked: list[str]
    amendments: int = 0
    accepted: list[Relaxation] = field(default_factory=list)
    """The relaxations its amendments accepted, in order."""
    snapshot: GraphSnapshot | None = None
    explained: list[ExplainerRun] = field(default_factory=list)
    """The explanation each plan revision waited for approval with."""
    started: float | None = None
    """When the brief was sent, after the models were fitted."""
    ended: float | None = None
    """When the session ended, before its plan was scored (ADR 0077)."""


class _Waited:
    """Wraps a provider and adds up the wall-clock seconds its calls take, answered or not:
    a session's time waiting on the LLM (ADR 0077)."""

    def __init__(self, inner: LLMProvider) -> None:
        self._inner = inner
        self.seconds = 0.0

    async def complete_structured[T: BaseModel](
        self, schema: type[T], messages: Sequence[Message]
    ) -> T:
        started = time.perf_counter()
        try:
            return await self._inner.complete_structured(schema, messages)
        finally:
            self.seconds += time.perf_counter() - started

    async def complete_with_tools(
        self, tools: Sequence[ToolSpec], messages: Sequence[Message]
    ) -> ToolTurn:
        started = time.perf_counter()
        try:
            return await self._inner.complete_with_tools(tools, messages)
        finally:
            self.seconds += time.perf_counter() - started


async def _run(
    scenario: Scenario,
    number: int,
    provider: LLMProvider,
    world: EvalWorld,
    settings: PlanningSettings,
    policy: CompanyPolicy,
    pricing: LLMPricing,
    benchmarks: Benchmarks,
) -> RunResult:
    started = time.perf_counter()
    session = _Session(route=[], asked=[])
    trace = MemoryTrace()
    session_id = uuid5(NAMESPACE_URL, f"promopilot:eval:{scenario.name}:{number}")
    waited = _Waited(provider)
    logged = MissLog(waited)
    try:
        try:
            outcome = await _play(
                scenario, session_id, logged, world, settings, policy, pricing, trace, session
            )
        finally:
            session.ended = time.perf_counter()
        result = await _score(scenario, number, outcome, session, world, policy)
        result = await _assess(scenario, result, session, benchmarks)
    except Exception as error:  # a failed session is a result, not the end of the eval
        result = RunResult(
            run=number,
            outcome=RunOutcome.FAILED,
            error=f"{type(error).__name__}: {error}",
            route=tuple(session.route),
            questions_asked=tuple(session.asked),
            amendments_applied=session.amendments,
            properties=tuple(
                check_property(prop, asked=session.asked, revision=None, flagged=_flagged(session))
                for prop in scenario.expect
            ),
        )
    ended = time.perf_counter()
    return result.model_copy(
        update={
            **_behaviour(scenario, session, result.outcome),
            "usage": session_usage(trace.of(session_id)),
            "cassette_misses": tuple(logged.misses),
            "session_s": (
                0.0
                if session.started is None or session.ended is None
                else session.ended - session.started
            ),
            "llm_s": waited.seconds,
            "duration_s": ended - started,
        }
    )


async def _play(
    scenario: Scenario,
    session_id: UUID,
    provider: LLMProvider,
    world: EvalWorld,
    settings: PlanningSettings,
    policy: CompanyPolicy,
    pricing: LLMPricing,
    trace: MemoryTrace,
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
        trace=trace,
        pricing=pricing,
    )
    graph = build_graph(tools, provider, InMemorySaver(serde=checkpoint_serializer()))
    thread = str(session_id)
    session.started = time.perf_counter()
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
            waiting, explained = snapshot.values.plan, snapshot.values.explanations
            if waiting is not None and explained is not None:
                session.explained.append(explainer_run(waiting.number, explained))
            if session.amendments == len(scenario.amendments):
                return RunOutcome.PLANNED
            amendment = scenario.amendments[session.amendments]
            if isinstance(amendment, str):
                session.amendments += 1
                session.route += await resume_with_amendment(graph, thread, amendment)
            else:
                relaxation = _accept(session, waiting)
                session.amendments += 1
                session.route += await resume_with_acceptance(graph, thread, relaxation)
        else:
            raise RuntimeError(f"the session stopped at {snapshot.paused_at or 'its end'}")


def _accept(session: _Session, waiting: PlanRevision | None) -> Relaxation:
    """The waiting revision's relaxation, accepted as `POST /amend {accept_relaxation: true}`
    accepts it (ADR 0052 D7, ADR 0070 D2, ADR 0083)."""
    if waiting is None:
        raise RuntimeError("the session awaits a decision without a plan revision")
    relaxation = acceptable_relaxation(waiting)
    if relaxation is None:
        raise RuntimeError(
            f"amendment {session.amendments + 1} accepts a relaxation, but plan revision "
            f"{waiting.number} has no relaxation to accept"
        )
    session.accepted.append(relaxation)
    return relaxation


async def _snapshot(graph: PlanningGraph, thread: str) -> GraphSnapshot:
    snapshot = await graph_state(graph, thread)
    if snapshot is None:
        raise RuntimeError("the session has no checkpoint")
    return snapshot


async def _score(
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
    kvi: tuple[str, ...] = ()
    wants_kvi = any(isinstance(prop, KviResponsePresent) for prop in scenario.expect)
    if wants_kvi and revision is not None and request is not None:
        kvi = await kvi_response(world.data(scenario.as_of_week), request, revision, policy=policy)
    substitutes: tuple[SubstitutePair, ...] = ()
    wants_substitutes = any(isinstance(p, NoStrongSubstitutesTogether) for p in scenario.expect)
    if wants_substitutes and request is not None:
        truth = world.ground_truth
        strong = strong_substitutes(truth.substitute_pairs, truth.cross_effects)
        products = await world.data(scenario.as_of_week).products()
        substitutes = strong_in_scope(strong, products, request.scope)
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
        open_issues=(
            tuple(issue.code.value for issue in state.critic_findings)
            if revision is not None and state is not None
            else ()
        ),
        properties=tuple(
            check_property(
                prop,
                asked=session.asked,
                revision=revision,
                flagged=_flagged(session),
                notes=state.planner_notes if state is not None else (),
                summary=state.explanations.summary
                if state is not None and state.explanations is not None
                else None,
                kvi=kvi,
                substitutes=substitutes,
            )
            for prop in scenario.expect
        ),
    )


def _flagged(session: _Session) -> tuple[str, ...]:
    """The fields whose assumption the session's latest reading flags."""
    if session.snapshot is None:
        return ()
    return tuple(dict.fromkeys(a.field for a in session.snapshot.values.assumptions if a.flagged))


def _behaviour(scenario: Scenario, session: _Session, outcome: RunOutcome) -> dict[str, object]:
    """The agent-behaviour checks of a session, whatever its outcome (#55): the final request
    against the labels, what it asked and flagged, and how it handled an infeasible request."""
    state = None if session.snapshot is None else session.snapshot.values
    planned = outcome is RunOutcome.PLANNED
    revision = state.plan if planned and state is not None else None
    flagged = _flagged(session)
    return {
        "extraction": match_fields(
            scenario.labels,
            None if state is None else state.request,
            accepted=session.accepted,
        ),
        "flagged": flagged,
        "clarification": check_clarification(scenario, asked=session.asked, flagged=flagged),
        "unneeded_asks": unneeded_asks(scenario, session.asked),
        "infeasibility": check_infeasibility(scenario, revision),
        "explanations": tuple(session.explained),
    }


async def _assess(
    scenario: Scenario, result: RunResult, session: _Session, benchmarks: Benchmarks
) -> RunResult:
    """A plan the oracle scored, against the rule-based baseline and the best plan for its
    final request (ADR 0063)."""
    state = None if session.snapshot is None else session.snapshot.values
    request = None if state is None else state.plan_request
    if result.oracle is None or request is None or result.revision is None:
        return result
    objective = result.oracle.incremental_profit + result.oracle.clearance_value
    quality = await benchmarks.assess(
        request, scenario.seed, objective, result.revision.solver_status
    )
    return result.model_copy(update={"quality": quality})


def _summary(revision: PlanRevision, request: PlanningRequest) -> RevisionSummary:
    return RevisionSummary(
        number=revision.number,
        lines=len(revision.lines),
        regions=tuple(dict.fromkeys(line.line.region for line in revision.lines)),
        solver_status=revision.solver_status,
        objective=revision.objective,
        promo_cost=sum(line.promo_cost for line in revision.lines),
        marketing_budget=request.marketing_budget,
        sku_ids=tuple(sorted({sku for line in revision.lines for sku in line.line.skus})),
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
