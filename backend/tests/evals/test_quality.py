"""Plan-quality metrics (SPEC §12.2, ADR 0063): Jaccard and regret by hand, the rule-based
baseline on hand-built sales, and the three metrics on hand-built runs."""

from collections.abc import Sequence
from typing import Any

import pandas as pd
import pytest

import promopilot.evals.quality as quality_module
from promopilot.agents import PlanningSettings
from promopilot.agents.tools.as_of import fixed_as_of_week
from promopilot.agents.tools.option_context import load_option_context
from promopilot.config import Settings
from promopilot.datagen import GeneratedDataset
from promopilot.domain import (
    BindingEvidence,
    CompanyPolicy,
    Mechanism,
    PlanLine,
    PlanningRequest,
    PromoPlan,
    PromoWindow,
    Region,
    Scope,
    SolveStatus,
    TargetSegment,
)
from promopilot.evals import EvalWorld, FittedModels
from promopilot.evals.quality import (
    Benchmarks,
    assess,
    best_plan,
    consistency,
    default_plan,
    jaccard,
    mean_pairwise_jaccard,
    plan_quality,
    regret,
    regret_breakdown,
    regret_metric,
    rule_based_plan,
)
from promopilot.evals.report import (
    BestPlanSummary,
    DefaultPlanSummary,
    PlanQuality,
    RegretBreakdown,
    RevisionSummary,
    RuleBasedSummary,
    RunOutcome,
    RunResult,
    ScenarioResult,
)
from promopilot.models.demand import OPTION_COLUMNS, DemandModel, Prediction, PredictionContext
from promopilot.models.relations import Relations
from promopilot.optimizer import FittedOptionFacts, OptimisationResult, generate_options, solve
from tests.conftest import SMALL_AS_OF

POLICY = CompanyPolicy()

# ---------------------------------------------------------------- Jaccard


def test_jaccard_is_the_shared_skus_over_all_the_skus_either_selects() -> None:
    assert jaccard({"A", "B"}, {"B", "C"}) == pytest.approx(1 / 3)
    assert jaccard({"A", "B", "C"}, {"A", "B", "C", "D"}) == pytest.approx(3 / 4)
    assert jaccard({"A"}, {"B"}) == 0.0
    assert jaccard({"A"}, set()) == 0.0


def test_two_empty_plans_agree_completely() -> None:
    assert jaccard(set(), set()) == 1.0


def test_consistency_of_several_runs_is_the_mean_over_every_pair() -> None:
    # {A,B} v {A,B} = 1, {A,B} v {A,C} = 1/3, {A,B} v {A,C} = 1/3: mean 5/9.
    runs = [{"A", "B"}, {"A", "B"}, {"A", "C"}]

    assert mean_pairwise_jaccard(runs) == pytest.approx((1 + 1 / 3 + 1 / 3) / 3)
    assert mean_pairwise_jaccard([{"A"}]) is None


# ---------------------------------------------------------------- regret


def test_regret_is_the_share_of_the_best_plans_profit_our_plan_misses() -> None:
    assert regret(best=100_000.0, ours=90_000.0) == pytest.approx(0.10)
    assert regret(best=80_000.0, ours=20_000.0) == pytest.approx(0.75)


def test_regret_is_signed_so_a_plan_beating_the_best_plan_shows_it() -> None:
    assert regret(best=100_000.0, ours=110_000.0) == pytest.approx(-0.10)


def test_regret_of_a_losing_plan_can_exceed_100_percent() -> None:
    assert regret(best=50_000.0, ours=-25_000.0) == pytest.approx(1.5)


def test_when_the_best_plan_earns_nothing_matching_it_is_no_regret_and_losing_is_full() -> None:
    assert regret(best=0.0, ours=0.0) == 0.0
    assert regret(best=0.0, ours=0.004) == 0.0
    assert regret(best=0.0, ours=-0.004) == 0.0  # within a paisa
    assert regret(best=0.0, ours=-500.0) == 1.0
    assert regret(best=-300.0, ours=-300.0) == 0.0
    assert regret(best=-300.0, ours=-400.0) == 1.0


# ---------------------------------------------------------------- regret by cause (ADR 0078)

OPT, FEAS, INF = SolveStatus.OPTIMAL, SolveStatus.FEASIBLE, SolveStatus.INFEASIBLE


def breakdown(
    best: float,
    default: float,
    ours: float,
    statuses: tuple[SolveStatus, SolveStatus, SolveStatus] = (OPT, OPT, OPT),
) -> RegretBreakdown | None:
    best_status, default_status, ours_status = statuses
    return regret_breakdown(
        best=best,
        default=default,
        ours=ours,
        best_status=best_status,
        default_status=default_status,
        ours_status=ours_status,
    )


def test_regret_splits_into_model_error_and_the_planners_choices() -> None:
    # Best ₹100k, the default sequence on the fitted models ₹80k, ours ₹50k: regret 50%, of
    # which (100 - 80) / 100 = 20% is model error and (80 - 50) / 100 = 30% the planner's.
    parts = breakdown(best=100_000.0, default=80_000.0, ours=50_000.0)

    assert parts == RegretBreakdown(model_error=0.20, planner=0.30, timeouts=0.0)


def test_the_parts_are_signed_and_sum_to_the_regret() -> None:
    # The planner beat the default sequence, and the fitted models beat the best plan.
    parts = breakdown(best=100_000.0, default=110_000.0, ours=120_000.0)

    assert parts is not None
    assert parts.model_error == pytest.approx(-0.10)
    assert parts.planner == pytest.approx(-0.10)
    total = parts.model_error + parts.planner + parts.timeouts
    assert total == pytest.approx(regret(best=100_000.0, ours=120_000.0))


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        # The best plan timed out: the model-error part is the timeout's.
        ((FEAS, OPT, OPT), (0.0, 0.30, 0.20)),
        # Ours timed out: the planner part is.
        ((OPT, OPT, FEAS), (0.20, 0.0, 0.30)),
        # The default sequence timed out: both parts are.
        ((OPT, FEAS, OPT), (0.0, 0.0, 0.50)),
        ((FEAS, OPT, FEAS), (0.0, 0.0, 0.50)),
    ],
    ids=["best", "ours", "default", "best_and_ours"],
)
def test_a_part_whose_either_plan_timed_out_is_the_timeouts(
    statuses: tuple[SolveStatus, SolveStatus, SolveStatus], expected: tuple[float, ...]
) -> None:
    parts = breakdown(best=100_000.0, default=80_000.0, ours=50_000.0, statuses=statuses)

    assert parts is not None
    assert (parts.model_error, parts.planner, parts.timeouts) == pytest.approx(expected)


def test_there_is_no_breakdown_when_the_best_plan_earns_nothing_or_a_side_is_infeasible() -> None:
    assert breakdown(best=0.004, default=0.0, ours=0.0) is None
    assert breakdown(best=-500.0, default=-100.0, ours=-800.0) is None
    assert breakdown(best=100.0, default=80.0, ours=50.0, statuses=(INF, OPT, OPT)) is None
    assert breakdown(best=100.0, default=80.0, ours=50.0, statuses=(OPT, INF, OPT)) is None


# ---------------------------------------------------------------- the rule-based baseline

AS_OF = 52
WINDOW = PromoWindow(start_week=53, end_week=58)
"""6 weeks: a plan line runs at most 4, and a SKU has one line per region."""


class FixedCosts:
    """A forecast whose every line costs its SKU's amount, whatever else it is."""

    def __init__(self, cost: dict[str, float]) -> None:
        self.cost = cost
        self.asked: list[PlanLine] = []

    def predict(self, options: Sequence[PlanLine], context: PredictionContext) -> Prediction:
        self.asked += options
        table = pd.DataFrame(0.0, index=range(len(options)), columns=OPTION_COLUMNS)
        table["promo_cost"] = [self.cost[line.sku_id] for line in options]
        return Prediction(options=table, segments=pd.DataFrame())


def products() -> pd.DataFrame:
    skus = [f"S{n:02d}" for n in range(1, 13)]
    return pd.DataFrame(
        {
            "sku_id": [*skus, "D01"],
            "category": ["Snacks"] * 12 + ["Dairy"],
            "base_price": 50.0,
            "unit_cost": 30.0,
        }
    )


def stores() -> pd.DataFrame:
    return pd.DataFrame(
        {"store_id": ["N1", "N2", "S1", "E1"], "region": ["North", "North", "South", "East"]}
    )


def sales() -> pd.DataFrame:
    """Units over weeks 40-51 (the 12 before the as-of week): S01 sells most, S12 least; S06
    and S07 tie. Sales outside those weeks, in East, or of Dairy do not count."""
    per_sku = {f"S{n:02d}": 130 - 10 * n for n in range(1, 13)} | {"S07": 70}
    rows = [
        {"week_id": week, "store_id": store, "sku_id": sku_id, "units": units / 36}
        for week in range(40, 52)
        for store in ("N1", "N2", "S1")
        for sku_id, units in per_sku.items()
    ]
    rows += [
        {"week_id": 39, "store_id": "N1", "sku_id": "S12", "units": 10_000},
        {"week_id": 52, "store_id": "N1", "sku_id": "S11", "units": 10_000},
        {"week_id": 45, "store_id": "E1", "sku_id": "S12", "units": 10_000},
        {"week_id": 45, "store_id": "N1", "sku_id": "D01", "units": 10_000},
    ]
    return pd.DataFrame(rows)


def baseline_request(
    budget: float, caps: dict[Region, float] | None = None, sku_ids: tuple[str, ...] = ()
) -> PlanningRequest:
    return PlanningRequest(
        as_of_week=AS_OF,
        scope=Scope(regions=(Region.NORTH, Region.SOUTH), categories=("Snacks",), sku_ids=sku_ids),
        promo_window=WINDOW,
        marketing_budget=budget,
        regional_budget_caps=caps or {},
    )


def test_the_baseline_is_20_percent_off_the_top_10_sellers_for_everyone_over_the_window() -> None:
    costs = FixedCosts(dict.fromkeys(products()["sku_id"], 1.0))

    plan = rule_based_plan(
        baseline_request(1e9),
        sales=sales(),
        stores=stores(),
        products=products(),
        forecast=costs,
        policy=POLICY,
    )

    # The tie between S06 and S07 (70 units each) goes to S06, the lower SKU id.
    assert plan.sku_ids == ("S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08", "S09", "S10")
    assert plan.dropped_sku_ids == ()
    assert len(plan.plan.lines) == 10 * 2  # SKUs x regions
    assert {line.mechanism for line in plan.plan.lines} == {Mechanism.PCT_OFF}
    assert {line.depth_pct for line in plan.plan.lines} == {20}
    assert {line.target_segment for line in plan.plan.lines} == {TargetSegment.ALL_CUSTOMERS}
    s01_north = [
        (line.start_week, line.duration_weeks)
        for line in plan.plan.lines
        if line.sku_id == "S01" and line.region is Region.NORTH
    ]
    assert s01_north == [(53, 4)]  # from the window's start, as long as a line may run
    assert plan.expected_promo_cost == pytest.approx(20.0)


def test_sellers_are_dropped_from_the_bottom_until_the_plan_fits_the_budget() -> None:
    # Each SKU's two lines cost 2 x its amount: S01-S10 cost 2 x 10 = 20 each, 200 in all.
    costs = FixedCosts(dict.fromkeys(products()["sku_id"], 10.0))

    plan = rule_based_plan(
        baseline_request(165.0),
        sales=sales(),
        stores=stores(),
        products=products(),
        forecast=costs,
        policy=POLICY,
    )

    assert plan.sku_ids == ("S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08")
    assert plan.dropped_sku_ids == ("S10", "S09")
    assert plan.expected_promo_cost == pytest.approx(160.0)


def test_a_regional_cap_drops_sellers_too() -> None:
    # North spends 10 per SKU: a ₹50 cap there keeps five.
    costs = FixedCosts(dict.fromkeys(products()["sku_id"], 10.0))

    plan = rule_based_plan(
        baseline_request(1e9, caps={Region.NORTH: 50.0}),
        sales=sales(),
        stores=stores(),
        products=products(),
        forecast=costs,
        policy=POLICY,
    )

    assert plan.sku_ids == ("S01", "S02", "S03", "S04", "S05")


def test_a_budget_nothing_fits_leaves_the_empty_plan() -> None:
    costs = FixedCosts(dict.fromkeys(products()["sku_id"], 10.0))

    plan = rule_based_plan(
        baseline_request(5.0),
        sales=sales(),
        stores=stores(),
        products=products(),
        forecast=costs,
        policy=POLICY,
    )

    assert plan.plan.lines == ()
    assert len(plan.dropped_sku_ids) == 10


def test_a_scope_naming_skus_ranks_only_those() -> None:
    costs = FixedCosts(dict.fromkeys(products()["sku_id"], 1.0))

    plan = rule_based_plan(
        baseline_request(1e9, sku_ids=("S12", "S03")),
        sales=sales(),
        stores=stores(),
        products=products(),
        forecast=costs,
        policy=POLICY,
    )

    assert plan.sku_ids == ("S03", "S12")


# ---------------------------------------------------------------- the three metrics


def quality(
    ours: float,
    rule_based: float,
    best: float | None,
    *,
    default: float | None = None,
    best_status: SolveStatus = SolveStatus.OPTIMAL,
    ours_status: SolveStatus = SolveStatus.OPTIMAL,
) -> PlanQuality:
    return assess(
        objective=ours,
        status=ours_status,
        rule_based=RuleBasedSummary(
            sku_ids=("A",),
            dropped_sku_ids=(),
            lines=1,
            expected_promo_cost=0.0,
            objective=rule_based,
        ),
        best=BestPlanSummary(
            solver_status=best_status if best is not None else SolveStatus.INFEASIBLE,
            lines=1,
            sku_ids=("A",),
            objective=best,
        ),
        default=DefaultPlanSummary(
            solver_status=SolveStatus.OPTIMAL,
            lines=1,
            sku_ids=("A",),
            objective=ours if default is None else default,
        ),
    )


def planned(number: int, q: PlanQuality | None, skus: tuple[str, ...] = ("A",)) -> RunResult:
    return RunResult(
        run=number,
        outcome=RunOutcome.PLANNED,
        revision=RevisionSummary(
            number=1,
            lines=len(skus),
            regions=(Region.NORTH,),
            solver_status=SolveStatus.OPTIMAL,
            objective=1.0,
            promo_cost=1.0,
            marketing_budget=2.0,
            sku_ids=skus,
        ),
        quality=q,
    )


def scenario(name: str, *runs: RunResult) -> ScenarioResult:
    return ScenarioResult(
        name=name, group="standard_festive", as_of_week=104, seed=0, runs=runs, passed=True
    )


def test_a_run_beats_ties_or_loses_to_the_baseline_by_more_than_a_paisa() -> None:
    assert quality(100.0, 50.0, 200.0).versus_rule_based == "beats"
    assert quality(100.0, 100.004, 200.0).versus_rule_based == "ties"
    assert quality(40.0, 50.0, 200.0).versus_rule_based == "loses"
    assert quality(100.0, 50.0, 200.0).regret == pytest.approx(0.5)
    assert quality(100.0, 50.0, 200.0).regret_rupees == pytest.approx(100.0)
    assert quality(100.0, 50.0, None).regret is None


def test_a_scored_run_carries_its_breakdown_and_which_plans_timed_out() -> None:
    q = quality(50.0, 0.0, 100.0, default=80.0)

    assert q.breakdown == RegretBreakdown(model_error=0.20, planner=0.30, timeouts=0.0)
    assert q.timed_out == ()
    timed_out = quality(50.0, 0.0, 100.0, best_status=FEAS, ours_status=FEAS)
    assert timed_out.timed_out == ("best", "ours")
    assert quality(50.0, 0.0, None).breakdown is None


def test_plan_quality_is_the_share_of_scenarios_whose_every_scored_run_beats_the_baseline() -> None:
    metric = plan_quality(
        [
            scenario("wins", planned(1, quality(100, 50, 200)), planned(2, quality(90, 50, 200))),
            scenario("split", planned(1, quality(100, 50, 200)), planned(2, quality(10, 50, 200))),
            scenario("tie", planned(1, quality(50, 50, 200))),
            scenario("unscored", planned(1, None)),
            scenario("wins too", planned(1, quality(1, 0, 2)), planned(2, None)),
        ]
    )

    assert (metric.value, metric.count, metric.of) == (0.5, 2, 4)
    assert (metric.target, metric.direction, metric.passed) == (0.9, "at_least", False)
    assert metric.breakdown == {"beats": 2, "ties": 1, "loses": 1}


def test_regret_is_the_median_over_scored_runs_against_at_most_10_percent() -> None:
    runs = [
        planned(1, quality(95, 0, 100)),  # 5%
        planned(2, quality(80, 0, 100)),  # 20%
        planned(3, quality(110, 0, 100)),  # -10%
        planned(4, quality(92, 0, 100)),  # 8%
        planned(5, quality(92, 0, None)),  # the best plan is infeasible
        planned(6, None),
        # The best plan timed out: a win against it is not a win (#157, ADR 0078).
        planned(7, quality(900, 0, 100, best_status=FEAS)),
        planned(8, quality(0, 0, 100, best_status=FEAS)),
    ]

    metric = regret_metric(runs)

    assert metric.value == pytest.approx((0.05 + 0.08) / 2)
    assert (metric.count, metric.of) == (3, 4)
    assert (metric.target, metric.direction, metric.passed) == (0.10, "at_most", True)
    assert metric.breakdown == {
        "best_infeasible": 1,
        "best_timed_out": 2,
        "largest_model_error": 1,
        "largest_planner": 0,
        "largest_timeouts": 0,
    }


def test_the_regret_metric_counts_the_largest_part_of_each_run_over_the_target() -> None:
    runs = [
        planned(1, quality(50, 0, 100, default=60)),  # model 40%, planner 10%
        planned(2, quality(50, 0, 100, default=90)),  # model 10%, planner 40%
        planned(3, quality(50, 0, 100, default=95, ours_status=FEAS)),  # timeouts 45%
        planned(4, quality(95, 0, 100)),  # within the target
    ]

    metric = regret_metric(runs)

    assert {k: v for k, v in metric.breakdown.items() if k.startswith("largest")} == {
        "largest_model_error": 1,
        "largest_planner": 1,
        "largest_timeouts": 1,
    }


def test_consistency_is_the_mean_scenario_jaccard_and_needs_two_runs() -> None:
    same = scenario("same", planned(1, None, ("A", "B")), planned(2, None, ("B", "A")))
    half = scenario("half", planned(1, None, ("A", "B")), planned(2, None, ("A", "C")))
    once = scenario("once", planned(1, None, ("A",)))

    metric = consistency([same, half, once])

    assert metric.value == pytest.approx((1 + 1 / 3) / 2)
    assert (metric.count, metric.of) == (1, 2)
    assert (metric.target, metric.direction, metric.passed) == (0.9, "at_least", False)


def test_with_one_run_per_scenario_consistency_is_not_scored() -> None:
    metric = consistency([scenario("once", planned(1, None, ("A",)))])

    assert (metric.value, metric.of, metric.passed) == (None, 0, None)


def test_runs_with_no_final_revision_are_left_out_of_consistency() -> None:
    failed = RunResult(run=2, outcome=RunOutcome.FAILED, error="boom")

    metric = consistency([scenario("s", planned(1, None, ("A",)), failed)])

    assert metric.value is None


# ---------------------------------------------------------------- the best plan

FREE = CompanyPolicy(margin_floor=0.10, fixed_cost_per_line_week=dict.fromkeys(Mechanism, 0.0))
"""Without fixed marketing costs, some of the small world's options pay for themselves."""
SETTINGS = PlanningSettings.from_settings(Settings(simulation_runs=200))
SNACKS_NORTH = PlanningRequest(
    as_of_week=SMALL_AS_OF,
    scope=Scope(regions=(Region.NORTH,), categories=("Snacks",)),
    promo_window=PromoWindow(start_week=SMALL_AS_OF + 1, end_week=SMALL_AS_OF + 2),
    marketing_budget=20_000,
)


@pytest.fixture
def world(
    small_dataset: GeneratedDataset, small_models: tuple[DemandModel, Relations]
) -> EvalWorld:
    return EvalWorld(small_dataset, fitted={SMALL_AS_OF: FittedModels(*small_models)})


async def test_the_best_plan_is_our_optimiser_on_true_parameter_predictions(
    world: EvalWorld,
) -> None:
    result = await best_plan(SNACKS_NORTH, world=world, settings=SETTINGS, seed=1, policy=FREE)
    true = world.oracle.evaluate(result.plan, SMALL_AS_OF, FREE)

    assert result.status is SolveStatus.OPTIMAL
    assert result.plan.lines
    snacks = set(world.dataset.products.loc[lambda p: p["category"] == "Snacks", "sku_id"])
    assert {line.sku_id for line in result.plan.lines} <= snacks
    assert {line.region for line in result.plan.lines} == {Region.NORTH}
    # Planned on the true demand, the optimiser's own objective is what the oracle scores.
    assert result.objective == pytest.approx(true.objective, rel=0.01)
    # No binding analysis: any constraint that could bind is left unproven.
    assert all(b.evidence is BindingEvidence.UNPROVEN for b in result.binding_constraints)


async def test_the_best_plan_beats_the_plan_the_fitted_models_choose(world: EvalWorld) -> None:
    best = await best_plan(SNACKS_NORTH, world=world, settings=SETTINGS, seed=1, policy=FREE)
    data = world.data(SMALL_AS_OF)
    models = await world.models(SMALL_AS_OF)
    loaded = await load_option_context(
        SNACKS_NORTH, models.demand, models.relations, data, fixed_as_of_week(SMALL_AS_OF), FREE
    )
    options = generate_options(SNACKS_NORTH, loaded.context)
    fitted = solve(SNACKS_NORTH, options, FittedOptionFacts(loaded.context), FREE, seed=1)

    def true(plan: PromoPlan) -> float:
        return world.oracle.evaluate(plan, SMALL_AS_OF, FREE).objective

    assert true(best.plan) > true(fitted.plan)
    # The default plan is exactly that: the default sequence on the fitted models.
    default = await default_plan(SNACKS_NORTH, world=world, settings=SETTINGS, seed=1, policy=FREE)
    assert default.plan == fitted.plan
    assert default.status is fitted.status


async def test_both_plans_are_computed_once_per_seed_and_request(
    world: EvalWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, int]] = []
    real_best, real_default = quality_module.best_plan, quality_module.default_plan

    async def counted_best(*args: Any, **kwargs: Any) -> OptimisationResult:
        calls.append(("best", kwargs["seed"]))
        return await real_best(*args, **kwargs)

    async def counted_default(*args: Any, **kwargs: Any) -> OptimisationResult:
        calls.append(("default", kwargs["seed"]))
        return await real_default(*args, **kwargs)

    monkeypatch.setattr(quality_module, "best_plan", counted_best)
    monkeypatch.setattr(quality_module, "default_plan", counted_default)
    benchmarks = Benchmarks(world, SETTINGS, FREE)

    first = await benchmarks.assess(SNACKS_NORTH, 1, objective=100.0, status=SolveStatus.OPTIMAL)
    second = await benchmarks.assess(SNACKS_NORTH, 1, objective=50.0, status=SolveStatus.OPTIMAL)

    assert sorted(calls) == [("best", 1), ("default", 1)]
    assert first.best == second.best
    assert first.default == second.default
    assert first.default is not None
    assert first.breakdown is not None
    assert first.regret is not None
    parts = first.breakdown
    assert parts.model_error + parts.planner + parts.timeouts == pytest.approx(first.regret)
    assert first.rule_based == second.rule_based
    assert first.best.objective is not None
    assert first.regret == pytest.approx(regret(first.best.objective, 100.0))
    assert second.objective == 50.0
    # 20% off the top sellers is priced on the fitted model and scored by the oracle.
    assert first.rule_based.lines == len(first.rule_based.sku_ids)
    assert first.rule_based.expected_promo_cost <= SNACKS_NORTH.marketing_budget
