"""Eval metrics as pure functions (SPEC §12.2, ADR 0056).

Constraint satisfaction is checked on plan-time values by `validate_plan`, which is independent
of the optimiser; the oracle breach rate is the share of the same plans whose true outcome
breaks a constraint, reported with no target (ADR 0012). Expected properties are checked on a
session's outcome.
"""

from collections.abc import Sequence

from promopilot.domain import CompanyPolicy, PlanningRequest, PlanRevision, SolveStatus, Violation
from promopilot.evals.oracle import PlanOutcome
from promopilot.evals.report import (
    Breach,
    ConstraintCheck,
    Metric,
    PropertyResult,
    RunResult,
)
from promopilot.evals.scenarios import (
    AsksClarification,
    DeclaresInfeasible,
    ExcludesRegion,
    ExpectedProperty,
)
from promopilot.guardrails import PlanFacts, plan_limits, validate_plan

ONE_PAISA = 0.01
"""Money within a paisa of its limit keeps it, as plan validation allows."""
_SCORED = (ConstraintCheck.PASSED, ConstraintCheck.FAILED)


def check_constraints(
    status: SolveStatus | None,
    facts: PlanFacts,
    request: PlanningRequest,
    policy: CompanyPolicy,
) -> tuple[ConstraintCheck, tuple[Violation, ...]]:
    """Whether the final plan keeps every hard constraint on its own plan-time numbers
    (ADR 0012). An infeasible revision is not scored: its closest plan misses a clearance
    target by construction."""
    if status is SolveStatus.INFEASIBLE:
        return ConstraintCheck.INFEASIBLE, ()
    violations = validate_plan(facts, request, policy)
    return (ConstraintCheck.FAILED if violations else ConstraintCheck.PASSED), violations


def oracle_breaches(
    outcome: PlanOutcome, request: PlanningRequest, policy: CompanyPolicy
) -> tuple[Breach, ...]:
    """The constraints the plan's true outcome breaks: true promo cost over the budget, true
    blended margin under the minimum (the brief's, never below the policy floor), and true
    demand above the available stock of any plan line (ADR 0012, ADR 0017)."""
    breaches = []
    if outcome.promo_cost > request.marketing_budget + ONE_PAISA:
        breaches.append(Breach.PROMO_COST_OVER_BUDGET)
    minimum = plan_limits(request, policy).min_margin
    if outcome.blended_margin is not None and outcome.blended_margin < minimum:
        breaches.append(Breach.MARGIN_BELOW_MINIMUM)
    if outcome.stock_capped_lines > 0:
        breaches.append(Breach.DEMAND_OVER_STOCK)
    return tuple(breaches)


def constraint_satisfaction(runs: Sequence[RunResult]) -> Metric:
    """The share of scored final plans that keep every hard constraint on their plan-time
    values; target 100% (SPEC §12.2, ADR 0012)."""
    scored = [run for run in runs if run.constraints in _SCORED]
    passed = sum(run.constraints is ConstraintCheck.PASSED for run in scored)
    value = _share(passed, len(scored))
    return Metric(
        name="constraint_satisfaction",
        label="Constraint satisfaction",
        value=value,
        count=passed,
        of=len(scored),
        target=1.0,
        direction="at_least",
        passed=None if value is None else value >= 1.0,
        breakdown={
            check.value: sum(run.constraints is check for run in runs)
            for check in (
                ConstraintCheck.FAILED,
                ConstraintCheck.INFEASIBLE,
                ConstraintCheck.NO_PLAN,
            )
        },
    )


def oracle_breach_rate(runs: Sequence[RunResult]) -> Metric:
    """The share of scored final plans whose true outcome breaks a constraint, with how many
    break each; reported, with no target (SPEC §12.2, ADR 0012)."""
    scored = [run.oracle for run in runs if run.oracle is not None]
    breached = sum(bool(score.breaches) for score in scored)
    return Metric(
        name="oracle_breach_rate",
        label="Oracle breach rate",
        value=_share(breached, len(scored)),
        count=breached,
        of=len(scored),
        breakdown={
            breach.value: sum(breach in score.breaches for score in scored) for breach in Breach
        },
    )


def check_property(
    prop: ExpectedProperty, *, asked: Sequence[str], revision: PlanRevision | None
) -> PropertyResult:
    """Whether a session's outcome has the property: the question ids it asked, and its final
    plan revision (None when it ended without one)."""
    described = prop.describe()
    if isinstance(prop, AsksClarification):
        passed = prop.asks_clarification in asked
        detail = f"asked about {', '.join(asked) or 'nothing'}"
        return PropertyResult(property=described, passed=passed, detail=detail)
    if revision is None:
        return PropertyResult(property=described, passed=False, detail="no final plan revision")
    if isinstance(prop, DeclaresInfeasible):
        infeasible = revision.solver_status is SolveStatus.INFEASIBLE
        status = revision.solver_status.value if revision.solver_status else "unknown"
        return PropertyResult(
            property=described,
            passed=infeasible == prop.declares_infeasible,
            detail=f"revision {revision.number} is {status}",
        )
    if isinstance(prop, ExcludesRegion):
        there = sum(line.line.region is prop.excludes_region for line in revision.lines)
        return PropertyResult(
            property=described,
            passed=there == 0,
            detail=f"revision {revision.number} has {there} plan line(s) in "
            f"{prop.excludes_region.value}",
        )
    missed = [s for s in revision.clearance_shortfalls if s.sku_id == prop.meets_clearance]
    detail = (
        ", ".join(
            f"{s.region.value} reaches {s.expected_sell_through:.2%} of a {s.target:.0%} "
            f"target, {s.shortfall_units:,.0f} units short"
            for s in missed
        )
        or f"no clearance shortfall in revision {revision.number}"
    )
    return PropertyResult(property=described, passed=not missed, detail=detail)


def _share(count: int, of: int) -> float | None:
    return None if of == 0 else count / of
