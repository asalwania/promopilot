"""Plan-quality metrics (SPEC §12.2, ADR 0063): whether plans beat a rule-based baseline, how
close they come to the best plan, and how alike a scenario's runs plan.

The harness builds both plans a final plan is compared with, from that run's final planning
request, never from anything a scenario author writes:

- the **rule-based baseline**: 20% off the top 10 sellers in scope (units over the 12 weeks
  before the as-of week, ties by SKU id), in every region of the scope, to All customers,
  over the promo window (its first 4 weeks when it is longer: a plan line runs at most 4,
  and a SKU has one line per region), with whole sellers dropped from the bottom until its
  expected
  promo cost, on the scenario's fitted demand model, fits the budget and every regional cap;
- the **best plan**: our own option generation and optimiser, unchanged, on true-parameter
  predictions (`TrueForecast`, `TrueRelations`) with the session's deterministic budgets and
  the scenario's seed, the binding analysis off;
- the **default plan**: the same, on the scenario's fitted models: the plan the default
  sequence makes for the request (ADR 0078).

The oracle scores them all on its objective, incremental profit plus clearance value
(ADR 0005). The three are computed once per scenario seed and final request.

Regret splits by cause (ADR 0078): model error (best - default) / best, the planner's choices
(default - ours) / best, and timeouts, the part whose plans include one the solver stopped as
FEASIBLE. The three sum to the regret.
"""

import asyncio
import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from itertools import combinations
from typing import Literal, Protocol

import pandas as pd

from promopilot.agents import PlanningSettings
from promopilot.agents.tools.as_of import fixed_as_of_week
from promopilot.agents.tools.option_context import load_option_context
from promopilot.domain import (
    CompanyPolicy,
    Mechanism,
    PlanLine,
    PlanningRequest,
    PromoPlan,
    Region,
    SolveStatus,
    TargetSegment,
)
from promopilot.evals.report import (
    BestPlanSummary,
    DefaultPlanSummary,
    Metric,
    PlanQuality,
    RegretBreakdown,
    RuleBasedSummary,
    RunResult,
    ScenarioResult,
    TimedOutPlan,
)
from promopilot.evals.truth_forecast import TrueForecast, TrueRelations
from promopilot.evals.world import EvalWorld
from promopilot.models.demand import Prediction, PredictionContext
from promopilot.optimizer import FittedOptionFacts, OptimisationResult, generate_options, solve

ONE_PAISA = 0.01
"""Money within a paisa of another amount is the same amount."""
TOP_SELLERS = 10
DEPTH_PCT = 20
SALES_WEEKS = 12
"""Top sellers are ranked on units over this many weeks before the as-of week."""
MAX_LINE_WEEKS = 4
"""A plan line runs at most 4 weeks, and a SKU has one line per region: a longer window is
covered from its start for 4 weeks."""

PLAN_QUALITY_TARGET = 0.9
REGRET_TARGET = 0.10
CONSISTENCY_TARGET = 0.9


# ---------------------------------------------------------------- consistency and regret


def jaccard(first: Iterable[str], second: Iterable[str]) -> float:
    """The SKUs both select over the SKUs either selects; two empty sets agree completely."""
    a, b = set(first), set(second)
    union = a | b
    return 1.0 if not union else len(a & b) / len(union)


def mean_pairwise_jaccard(sets: Sequence[Iterable[str]]) -> float | None:
    """The mean Jaccard of every two of the sets; None with fewer than two."""
    if len(sets) < 2:
        return None
    return statistics.fmean(jaccard(a, b) for a, b in combinations(sets, 2))


def regret(best: float, ours: float) -> float:
    """(best - ours) / best: the share of the best plan's oracle profit ours misses (SPEC
    §12.2), signed, so a plan that beats the best plan's approximations shows below 0.

    When the best plan earns a paisa or less, matching it is no regret and earning less is
    all of it (1)."""
    if best <= ONE_PAISA:
        return 0.0 if ours >= best - ONE_PAISA else 1.0
    return (best - ours) / best


def regret_breakdown(
    *,
    best: float,
    default: float,
    ours: float,
    best_status: SolveStatus,
    default_status: SolveStatus,
    ours_status: SolveStatus | None,
) -> RegretBreakdown | None:
    """The regret (best - ours) / best by cause (ADR 0078), each part a signed share of the
    best plan's oracle objective:

    - model error, (best - default) / best: the same optimiser on the fitted models against
      the true parameters;
    - the planner's choices, (default - ours) / best: the planner agent's plan against the
      default sequence's;
    - timeouts: each of those two parts whose two plans include one the solver stopped as
      FEASIBLE on its work budget.

    They sum to the regret. None when the best plan earns a paisa or less (the regret is then
    0 or 1, not a share) or the best or the default plan is infeasible."""
    if best <= ONE_PAISA or SolveStatus.INFEASIBLE in (best_status, default_status):
        return None
    model_error, planner, timeouts = (best - default) / best, (default - ours) / best, 0.0
    if SolveStatus.FEASIBLE in (best_status, default_status):
        model_error, timeouts = 0.0, timeouts + model_error
    if SolveStatus.FEASIBLE in (default_status, ours_status):
        planner, timeouts = 0.0, timeouts + planner
    return RegretBreakdown(model_error=model_error, planner=planner, timeouts=timeouts)


def assess(
    *,
    objective: float,
    status: SolveStatus | None,
    rule_based: RuleBasedSummary,
    best: BestPlanSummary,
    default: DefaultPlanSummary,
) -> PlanQuality:
    """Our plan's oracle objective and solver status against the rule-based baseline's, the
    best plan's and the default plan's."""
    gap = objective - rule_based.objective
    versus: Literal["beats", "ties", "loses"] = (
        "beats" if gap > ONE_PAISA else "loses" if gap < -ONE_PAISA else "ties"
    )
    top = best.objective
    statuses: dict[TimedOutPlan, SolveStatus | None] = {
        "best": best.solver_status,
        "default": default.solver_status,
        "ours": status,
    }
    return PlanQuality(
        objective=objective,
        rule_based=rule_based,
        best=best,
        versus_rule_based=versus,
        regret=None if top is None else regret(top, objective),
        regret_rupees=None if top is None else top - objective,
        default=default,
        breakdown=None
        if top is None
        else regret_breakdown(
            best=top,
            default=default.objective,
            ours=objective,
            best_status=best.solver_status,
            default_status=default.solver_status,
            ours_status=status,
        ),
        timed_out=tuple(plan for plan, s in statuses.items() if s is SolveStatus.FEASIBLE),
    )


def scenario_consistency(runs: Sequence[RunResult]) -> float | None:
    """The mean pairwise Jaccard of the SKUs the runs' final revisions promote; runs with no
    final revision are left out."""
    return mean_pairwise_jaccard([run.revision.sku_ids for run in runs if run.revision])


# ---------------------------------------------------------------- the rule-based baseline


class CostForecast(Protocol):
    """What the baseline's budget check needs (`DemandModel.predict`)."""

    def predict(self, options: Sequence[PlanLine], context: PredictionContext) -> Prediction: ...


@dataclass(frozen=True)
class RuleBasedPlan:
    plan: PromoPlan
    sku_ids: tuple[str, ...]
    """The sellers promoted, the best first."""
    dropped_sku_ids: tuple[str, ...]
    """Top sellers dropped to fit the budget, the first dropped first."""
    expected_promo_cost: float


def rule_based_plan(
    request: PlanningRequest,
    *,
    sales: pd.DataFrame,
    stores: pd.DataFrame,
    products: pd.DataFrame,
    forecast: CostForecast,
    policy: CompanyPolicy,
) -> RuleBasedPlan:
    """20% off the top 10 sellers in the request's scope, to All customers, over its promo
    window (at most its first 4 weeks) in every region of its scope; whole sellers dropped
    from the bottom until the expected promo cost fits the marketing budget and every
    regional cap.

    `sales` has week_id, store_id, sku_id and units (`sales_weekly`); `stores` store_id and
    region; `products` sku_id and category.
    """
    scope = request.scope
    in_scope = products[products["category"].isin(scope.categories)]
    if scope.sku_ids:
        in_scope = in_scope[in_scope["sku_id"].isin(scope.sku_ids)]
    regions = {region.value for region in scope.regions}
    in_regions = stores.loc[stores["region"].isin(regions), "store_id"]
    first = request.as_of_week - SALES_WEEKS
    recent = sales[
        sales["week_id"].between(first, request.as_of_week - 1) & sales["store_id"].isin(in_regions)
    ]
    units = recent.groupby("sku_id")["units"].sum()
    ranked = pd.DataFrame({"sku_id": in_scope["sku_id"].astype(str)})
    ranked["units"] = ranked["sku_id"].map(units).fillna(0.0)
    ranked = ranked.sort_values(["units", "sku_id"], ascending=[False, True])
    top = list(ranked["sku_id"].head(TOP_SELLERS))

    window = request.promo_window
    duration = min(MAX_LINE_WEEKS, window.end_week - window.start_week + 1)
    lines = {
        sku_id: [
            PlanLine(
                sku_id=sku_id,
                region=region,
                mechanism=Mechanism.PCT_OFF,
                depth_pct=DEPTH_PCT,
                duration_weeks=duration,
                start_week=window.start_week,
                target_segment=TargetSegment.ALL_CUSTOMERS,
            )
            for region in scope.regions
        ]
        for sku_id in top
    }
    every = [line for sku_id in top for line in lines[sku_id]]
    costs = (
        forecast.predict(every, PredictionContext(policy=policy)).options["promo_cost"].tolist()
        if every
        else []
    )
    spend: dict[str, dict[Region, float]] = {sku_id: {} for sku_id in top}
    for line, cost in zip(every, costs, strict=True):
        by_region = spend[line.sku_id]
        by_region[line.region] = by_region.get(line.region, 0.0) + float(cost)

    kept, dropped = list(top), []
    while kept and not _fits(request, [spend[sku_id] for sku_id in kept]):
        dropped.append(kept.pop())
    return RuleBasedPlan(
        plan=PromoPlan(lines=tuple(line for sku_id in kept for line in lines[sku_id])),
        sku_ids=tuple(kept),
        dropped_sku_ids=tuple(dropped),
        expected_promo_cost=sum(sum(spend[sku_id].values()) for sku_id in kept),
    )


def _fits(request: PlanningRequest, spends: list[dict[Region, float]]) -> bool:
    total = sum(sum(spend.values()) for spend in spends)
    if total > request.marketing_budget + ONE_PAISA:
        return False
    return all(
        sum(spend.get(region, 0.0) for spend in spends) <= cap + ONE_PAISA
        for region, cap in request.regional_budget_caps.items()
    )


# ---------------------------------------------------------------- the best plan


async def best_plan(
    request: PlanningRequest,
    *,
    world: EvalWorld,
    settings: PlanningSettings,
    seed: int,
    policy: CompanyPolicy,
) -> OptimisationResult:
    """Our optimiser on true-parameter predictions: every option `generate_options` would
    offer for the request, predicted by the true demand function with the true relations,
    selected by `solve` with the session's work budgets and `seed`, no binding analysis.

    Stock, competitor gaps and the catalogue are what a session sees at the request's as-of
    week."""
    return await _optimised(
        request, world=world, settings=settings, seed=seed, policy=policy, truth=True
    )


async def default_plan(
    request: PlanningRequest,
    *,
    world: EvalWorld,
    settings: PlanningSettings,
    seed: int,
    policy: CompanyPolicy,
) -> OptimisationResult:
    """The default sequence's plan for the request (ADR 0078): `best_plan` on the scenario's
    fitted models instead of the truth. The default sequence also runs the binding analysis,
    which only explains the plan, so it stays off here."""
    return await _optimised(
        request, world=world, settings=settings, seed=seed, policy=policy, truth=False
    )


async def _optimised(
    request: PlanningRequest,
    *,
    world: EvalWorld,
    settings: PlanningSettings,
    seed: int,
    policy: CompanyPolicy,
    truth: bool,
) -> OptimisationResult:
    week = request.as_of_week
    data = world.data(week)
    models = await world.models(week)
    loaded = await load_option_context(
        request, models.demand, models.relations, data, fixed_as_of_week(week), policy
    )
    context = loaded.context
    if truth:
        true = world.dataset.ground_truth
        context = replace(
            context,
            demand_model=TrueForecast(true, world.dataset.products, week),
            relations=TrueRelations(true),
        )
    options = await asyncio.to_thread(generate_options, request, context)
    solver = replace(settings.solver, binding_deterministic_limit=0.0)
    return await asyncio.to_thread(
        solve, request, options, FittedOptionFacts(context), policy, settings=solver, seed=seed
    )


class Benchmarks:
    """The rule-based baseline, the best plan and the default plan of each (seed, final
    request), computed the first time a run asks, and every final plan assessed against
    them."""

    def __init__(self, world: EvalWorld, settings: PlanningSettings, policy: CompanyPolicy):
        self._world = world
        self._settings = settings
        self._policy = policy
        self._computed: dict[
            tuple[int, str], tuple[RuleBasedSummary, BestPlanSummary, DefaultPlanSummary]
        ] = {}

    async def assess(
        self, request: PlanningRequest, seed: int, objective: float, status: SolveStatus | None
    ) -> PlanQuality:
        """Our final plan's oracle objective and solver status against the three plans for
        its request."""
        key = (seed, request.model_dump_json())
        if key not in self._computed:
            self._computed[key] = (
                await self._rule_based(request),
                await self._best(request, seed),
                await self._default(request, seed),
            )
        rule_based, best, default = self._computed[key]
        return assess(
            objective=objective, status=status, rule_based=rule_based, best=best, default=default
        )

    async def _rule_based(self, request: PlanningRequest) -> RuleBasedSummary:
        dataset = self._world.dataset
        _, demand = await (await self._world.models(request.as_of_week)).demand.get()
        plan = rule_based_plan(
            request,
            sales=dataset.sales_weekly,
            stores=dataset.stores,
            products=dataset.products,
            forecast=demand,
            policy=self._policy,
        )
        return RuleBasedSummary(
            sku_ids=plan.sku_ids,
            dropped_sku_ids=plan.dropped_sku_ids,
            lines=len(plan.plan.lines),
            expected_promo_cost=plan.expected_promo_cost,
            objective=self._objective(plan.plan, request.as_of_week),
        )

    async def _best(self, request: PlanningRequest, seed: int) -> BestPlanSummary:
        result = await best_plan(
            request, world=self._world, settings=self._settings, seed=seed, policy=self._policy
        )
        infeasible = result.status is SolveStatus.INFEASIBLE
        return BestPlanSummary(
            solver_status=result.status,
            lines=len(result.plan.lines),
            sku_ids=tuple(sorted({sku for line in result.plan.lines for sku in line.skus})),
            objective=None if infeasible else self._objective(result.plan, request.as_of_week),
        )

    async def _default(self, request: PlanningRequest, seed: int) -> DefaultPlanSummary:
        result = await default_plan(
            request, world=self._world, settings=self._settings, seed=seed, policy=self._policy
        )
        return DefaultPlanSummary(
            solver_status=result.status,
            lines=len(result.plan.lines),
            sku_ids=tuple(sorted({sku for line in result.plan.lines for sku in line.skus})),
            objective=self._objective(result.plan, request.as_of_week),
        )

    def _objective(self, plan: PromoPlan, as_of_week: int) -> float:
        return self._world.oracle.evaluate(plan, as_of_week, self._policy).objective


# ---------------------------------------------------------------- the metrics


def plan_quality(scenarios: Sequence[ScenarioResult]) -> Metric:
    """The share of scenarios whose every scored run beats the rule-based baseline by more
    than a paisa; target ≥ 90% (SPEC §12.2). A scenario with a losing run loses; one with
    neither a losing run nor every run beating ties. Scenarios with no scored run are left
    out."""
    counts = {"beats": 0, "ties": 0, "loses": 0}
    for scenario in scenarios:
        verdicts = {run.quality.versus_rule_based for run in scenario.runs if run.quality}
        if not verdicts:
            continue
        verdict = "beats" if verdicts == {"beats"} else "loses" if "loses" in verdicts else "ties"
        counts[verdict] += 1
    scored = sum(counts.values())
    value = None if scored == 0 else counts["beats"] / scored
    return Metric(
        name="plan_quality",
        label="Plan quality (beats the rule-based baseline)",
        value=value,
        count=counts["beats"],
        of=scored,
        target=PLAN_QUALITY_TARGET,
        direction="at_least",
        passed=None if value is None else value >= PLAN_QUALITY_TARGET,
        breakdown=counts,
    )


def regret_metric(runs: Sequence[RunResult]) -> Metric:
    """The median regret over scored runs whose best plan is feasible and did not time out;
    target ≤ 10% (SPEC §12.2). Its count is the runs within the target.

    Its breakdown counts the runs left out, `best_infeasible` and `best_timed_out` (beating a
    best plan that timed out is not a win, ADR 0078), and, for each counted run above the
    target, its largest part: `largest_model_error`, `largest_planner` or `largest_timeouts`."""
    counted = [
        run.quality
        for run in runs
        if run.quality and run.quality.regret is not None and "best" not in run.quality.timed_out
    ]
    regrets = [quality.regret for quality in counted if quality.regret is not None]
    value = statistics.median(regrets) if regrets else None
    largest = {"largest_model_error": 0, "largest_planner": 0, "largest_timeouts": 0}
    for quality in counted:
        parts = quality.breakdown
        if parts is None or quality.regret is None or quality.regret <= REGRET_TARGET:
            continue
        by_part = {
            "largest_model_error": parts.model_error,
            "largest_planner": parts.planner,
            "largest_timeouts": parts.timeouts,
        }
        largest[max(by_part, key=by_part.__getitem__)] += 1
    return Metric(
        name="regret",
        label="Regret (median, against the best plan)",
        value=value,
        count=sum(r <= REGRET_TARGET for r in regrets),
        of=len(regrets),
        target=REGRET_TARGET,
        direction="at_most",
        passed=None if value is None else value <= REGRET_TARGET,
        breakdown={
            "best_infeasible": sum(
                run.quality is not None and run.quality.regret is None for run in runs
            ),
            "best_timed_out": sum(
                run.quality is not None
                and run.quality.regret is not None
                and "best" in run.quality.timed_out
                for run in runs
            ),
            **largest,
        },
    )


def consistency(scenarios: Sequence[ScenarioResult]) -> Metric:
    """The mean over scenarios of the mean pairwise Jaccard of their runs' selected SKUs;
    target ≥ 0.9 (SPEC §12.2). Scenarios with fewer than two runs with a final revision are
    left out, so with one run per scenario it is not scored. Its count is the scenarios at
    the target."""
    values = [v for v in (scenario_consistency(s.runs) for s in scenarios) if v is not None]
    value = statistics.fmean(values) if values else None
    return Metric(
        name="consistency",
        label="Consistency (Jaccard of selected SKUs across runs)",
        value=value,
        count=sum(v >= CONSISTENCY_TARGET for v in values),
        of=len(values),
        target=CONSISTENCY_TARGET,
        direction="at_least",
        passed=None if value is None else value >= CONSISTENCY_TARGET,
    )
