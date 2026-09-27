"""`simulate` on hand-built response rows: every input pinned, invariants and hand-computed limits
checked through the result only (SPEC §9.5, ADR 0042)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from promopilot.domain import (
    CompanyPolicy,
    Mechanism,
    PlanLine,
    PlanSimulation,
    PromoPlan,
    Region,
    TargetSegment,
)
from promopilot.economics import effective_unit_price
from promopilot.models.demand import PredictionContext, ResponseRows
from promopilot.simulator import SimulationInputs, simulate

FREE = CompanyPolicy(fixed_cost_per_line_week=dict.fromkeys(Mechanism, 0.0))
PRICES = {"A": 100.0, "B": 50.0, "C": 80.0}
COSTS = {"A": 60.0, "B": 30.0, "C": 50.0}
HUGE = 1e9
"""A negative binomial size this large is Poisson noise: tiny next to the means used here."""


@dataclass(frozen=True)
class HandBuilt:
    """Response rows with one term, beta x log(p / base price), per store and promo week."""

    beta: float = -2.0
    beta_se: float = 0.0
    dispersion: float = HUGE
    baseline: Mapping[str, float] = field(default_factory=lambda: {"S1": 1_000.0})
    """Baseline units per store and week."""

    def response_rows(
        self, options: Sequence[PlanLine], context: PredictionContext
    ) -> ResponseRows:
        records = []
        for n, line in enumerate(options):
            for sku_id in line.skus:
                price = effective_unit_price(line.mechanism, PRICES[sku_id], line.depth_pct)
                for store_id, baseline in self.baseline.items():
                    for week in range(line.start_week, line.start_week + line.duration_weeks):
                        records.append(
                            {
                                "option": n,
                                "sku_id": sku_id,
                                "anchor": sku_id == line.sku_id,
                                "store_id": store_id,
                                "segment": "Families",
                                "week_id": week,
                                "price": price,
                                "base_price": PRICES[sku_id],
                                "unit_cost": COSTS[sku_id],
                                "baseline_units": baseline,
                            }
                        )
        rows = pd.DataFrame(records)
        skus = sorted(PRICES)
        return ResponseRows(
            rows=rows,
            design=pd.DataFrame({"beta": np.log(rows["price"] / rows["base_price"])}),
            estimate=pd.DataFrame({"beta": self.beta}, index=skus),
            std_error=pd.DataFrame({"beta": self.beta_se}, index=skus),
            dispersion=pd.Series(self.dispersion, index=skus),
        )


def line(
    sku_id: str = "A",
    *,
    region: Region = Region.NORTH,
    depth_pct: int = 20,
    duration_weeks: int = 2,
    mechanism: Mechanism = Mechanism.PCT_OFF,
    partner: str | None = None,
) -> PlanLine:
    return PlanLine(
        sku_id=sku_id,
        region=region,
        mechanism=mechanism,
        depth_pct=depth_pct,
        duration_weeks=duration_weeks,
        start_week=110,
        target_segment=TargetSegment.ALL_CUSTOMERS,
        bundle_partner_sku_id=partner,
    )


def stock(available: Mapping[tuple[str, Region], float]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"sku_id": sku_id, "region": region.value, "available_stock": units}
            for (sku_id, region), units in available.items()
        ],
        columns=["sku_id", "region", "available_stock"],
    )


AMPLE = 1e9


def inputs(
    demand: HandBuilt | None = None,
    available: Mapping[tuple[str, Region], float] | None = None,
    policy: CompanyPolicy = FREE,
) -> SimulationInputs:
    if available is None:
        available = {(sku, region): AMPLE for sku in PRICES for region in Region}
    return SimulationInputs(demand=demand or HandBuilt(), stock=stock(available), policy=policy)


def run(
    plan: PromoPlan, given_inputs: SimulationInputs, *, n_runs: int = 1_000, seed: int = 7
) -> PlanSimulation:
    return simulate(plan, given_inputs, n_runs=n_runs, seed=seed)


def expected_units(demand: HandBuilt, planned: PlanLine) -> float:
    """Σ over stores and weeks of baseline x exp(beta x log(p / base)), by hand."""
    price = effective_unit_price(planned.mechanism, PRICES[planned.sku_id], planned.depth_pct)
    lift = float(np.exp(demand.beta * np.log(price / PRICES[planned.sku_id])))
    return sum(demand.baseline.values()) * planned.duration_weeks * lift


NOISY = HandBuilt(beta=-2.0, beta_se=0.4, dispersion=2.0, baseline={"S1": 30.0, "S2": 20.0})


def test_the_same_seed_gives_identical_results() -> None:
    plan = PromoPlan(lines=(line("A"), line("B", region=Region.WEST)))

    first = run(plan, inputs(NOISY), seed=3)
    second = run(plan, inputs(NOISY), seed=3)

    assert first == second
    assert first.seed == 3
    assert first.n_runs == 1_000


def test_a_different_seed_gives_different_samples() -> None:
    plan = PromoPlan(lines=(line("A"),))

    first = run(plan, inputs(NOISY), seed=3)
    second = run(plan, inputs(NOISY), seed=4)

    assert first.lines[0].units != second.lines[0].units


def test_with_no_parameter_uncertainty_and_huge_dispersion_p50_is_the_expected_value() -> None:
    demand = HandBuilt(beta=-2.5, beta_se=0.0, dispersion=HUGE, baseline={"S1": 800, "S2": 400})
    planned = line("A", depth_pct=20, duration_weeks=3)

    result = run(PromoPlan(lines=(planned,)), inputs(demand))

    expected = expected_units(demand, planned)
    price = 80.0
    simulated = result.lines[0]
    assert simulated.units.p50 == pytest.approx(expected, rel=0.01)
    assert simulated.revenue.p50 == pytest.approx(expected * price, rel=0.01)
    assert simulated.gross_profit.p50 == pytest.approx(expected * (price - 60.0), rel=0.01)
    assert simulated.margin.p50 == pytest.approx((price - 60.0) / price)
    assert simulated.promo_spend.p50 == pytest.approx(expected * (100.0 - price), rel=0.01)
    assert result.total.units.p50 == pytest.approx(expected, rel=0.01)


def test_parameter_uncertainty_widens_the_range() -> None:
    plan = PromoPlan(lines=(line("A"),))
    sure = HandBuilt(beta_se=0.0, dispersion=HUGE)
    unsure = HandBuilt(beta_se=0.5, dispersion=HUGE)

    narrow = run(plan, inputs(sure)).lines[0].units
    wide = run(plan, inputs(unsure)).lines[0].units

    assert wide.p90 - wide.p10 > 5 * (narrow.p90 - narrow.p10)


def test_stock_out_probability_is_zero_with_ample_stock() -> None:
    plan = PromoPlan(lines=(line("A"), line("B", region=Region.WEST)))

    result = run(plan, inputs(NOISY))

    assert [simulated.stockout_probability for simulated in result.lines] == [0.0, 0.0]
    assert {r.region: r.stockout_probability for r in result.regions} == {
        Region.NORTH: 0.0,
        Region.WEST: 0.0,
    }


def test_stock_out_probability_is_one_with_no_stock() -> None:
    plan = PromoPlan(lines=(line("A"), line("B", region=Region.WEST)))
    available = {("A", Region.NORTH): 0.0, ("B", Region.WEST): AMPLE}

    result = run(plan, inputs(NOISY, available))

    assert [simulated.stockout_probability for simulated in result.lines] == [1.0, 0.0]
    assert {r.region: r.stockout_probability for r in result.regions} == {
        Region.NORTH: 1.0,
        Region.WEST: 0.0,
    }
    assert result.lines[0].units.p90 == 0.0
    assert result.lines[0].sell_through is None


def test_a_sku_with_no_stock_row_has_no_stock() -> None:
    result = run(PromoPlan(lines=(line("A"),)), inputs(NOISY, {}))

    assert result.lines[0].stockout_probability == 1.0
    assert result.lines[0].units.p90 == 0.0


def test_units_are_capped_at_pooled_regional_stock_and_money_follows_the_capped_units() -> None:
    # Two stores each want ~1,000 units a week: the region's 1,500 pooled units cap the line,
    # though either store's demand alone would fit.
    demand = HandBuilt(beta=0.0, baseline={"S1": 1_000.0, "S2": 1_000.0})
    planned = line("A", depth_pct=20, duration_weeks=1)
    policy = CompanyPolicy(fixed_cost_per_line_week=dict.fromkeys(Mechanism, 500.0))

    result = run(
        PromoPlan(lines=(planned,)), inputs(demand, {("A", Region.NORTH): 1_500.0}, policy)
    )

    simulated = result.lines[0]
    assert (simulated.units.p10, simulated.units.p50, simulated.units.p90) == pytest.approx(
        (1_500.0, 1_500.0, 1_500.0)
    )
    assert simulated.stockout_probability == 1.0
    assert simulated.sell_through is not None
    assert simulated.sell_through.p50 == pytest.approx(1.0)
    assert simulated.revenue.p50 == pytest.approx(1_500 * 80.0)
    assert simulated.gross_profit.p50 == pytest.approx(1_500 * 20.0)
    assert simulated.promo_spend.p50 == pytest.approx(1_500 * 20.0 + 500.0)


def test_negative_available_stock_counts_as_none() -> None:
    result = run(PromoPlan(lines=(line("A"),)), inputs(NOISY, {("A", Region.NORTH): -40.0}))

    assert result.lines[0].stockout_probability == 1.0
    assert result.lines[0].units.p90 == 0.0


def test_a_bundle_counts_its_partners_money_but_only_its_anchors_units() -> None:
    demand = HandBuilt(beta=0.0, baseline={"S1": 100.0})
    planned = line("A", mechanism=Mechanism.BUNDLE, depth_pct=20, duration_weeks=1, partner="B")
    available = {("A", Region.NORTH): 60.0, ("B", Region.NORTH): 50.0}

    result = run(PromoPlan(lines=(planned,)), inputs(demand, available))

    simulated = result.lines[0]
    # Both SKUs sell out: A's 60 units at ₹80, B's 50 at ₹40.
    assert simulated.units.p50 == pytest.approx(60.0)
    assert simulated.revenue.p50 == pytest.approx(60 * 80.0 + 50 * 40.0)
    assert simulated.gross_profit.p50 == pytest.approx(60 * 20.0 + 50 * 10.0)
    assert simulated.promo_spend.p50 == pytest.approx(60 * 20.0 + 50 * 10.0)
    assert simulated.sell_through is not None
    assert simulated.sell_through.p50 == pytest.approx(1.0)
    assert simulated.stockout_probability == 1.0


def test_a_bundle_stocks_out_when_only_its_partner_runs_out() -> None:
    demand = HandBuilt(beta=0.0, baseline={"S1": 100.0})
    planned = line("A", mechanism=Mechanism.BUNDLE, depth_pct=20, duration_weeks=1, partner="B")
    available = {("A", Region.NORTH): AMPLE, ("B", Region.NORTH): 10.0}

    result = run(PromoPlan(lines=(planned,)), inputs(demand, available))

    assert result.lines[0].stockout_probability == 1.0


def test_plan_totals_are_quantiles_of_each_runs_sum() -> None:
    demand = HandBuilt(beta=0.0, baseline={"S1": 100.0})
    plan = PromoPlan(lines=(line("A", duration_weeks=1), line("B", duration_weeks=1)))
    available = {("A", Region.NORTH): 40.0, ("B", Region.NORTH): 60.0}

    result = run(plan, inputs(demand, available))

    total = result.total
    assert total.units.p50 == pytest.approx(100.0)
    assert total.revenue.p50 == pytest.approx(40 * 80.0 + 60 * 40.0)
    assert total.gross_profit.p50 == pytest.approx(40 * 20.0 + 60 * 10.0)
    assert total.margin.p50 == pytest.approx((40 * 20.0 + 60 * 10.0) / (40 * 80.0 + 60 * 40.0))
    assert total.promo_spend.p50 == pytest.approx(40 * 20.0 + 60 * 10.0)
    assert total.sell_through is not None
    assert total.sell_through.p50 == pytest.approx(1.0)
    assert [r.region for r in result.regions] == [Region.NORTH]
    assert result.regions[0].stockout_probability == 1.0


def test_lines_are_reported_in_plan_order() -> None:
    plan = PromoPlan(lines=(line("C"), line("A", region=Region.WEST), line("B")))

    result = run(plan, inputs(NOISY), n_runs=100)

    assert [(s.sku_id, s.region) for s in result.lines] == [
        ("C", Region.NORTH),
        ("A", Region.WEST),
        ("B", Region.NORTH),
    ]
    assert [r.region for r in result.regions] == [Region.NORTH, Region.WEST]


def test_an_empty_plan_simulates_to_zero() -> None:
    result = run(PromoPlan(), inputs(NOISY), n_runs=100)

    assert result.lines == ()
    assert result.regions == ()
    assert result.total.units.p90 == 0.0
    assert result.total.revenue.p90 == 0.0
    assert result.total.sell_through is None


@st.composite
def small_plans(draw: st.DrawFn) -> tuple[PromoPlan, HandBuilt, dict[tuple[str, Region], float]]:
    skus = draw(st.lists(st.sampled_from(sorted(PRICES)), min_size=1, max_size=3, unique=True))
    lines = tuple(
        line(
            sku_id,
            region=draw(st.sampled_from(list(Region))),
            depth_pct=draw(st.sampled_from([5, 10, 20, 30, 40])),
            duration_weeks=draw(st.integers(1, 4)),
        )
        for sku_id in skus
    )
    demand = HandBuilt(
        beta=draw(st.floats(-4.0, 0.0)),
        beta_se=draw(st.floats(0.0, 1.0)),
        dispersion=draw(st.floats(0.5, 1_000.0)),
        baseline={
            "S1": draw(st.floats(0.0, 50.0)),
            "S2": draw(st.floats(0.0, 50.0)),
        },
    )
    available = {
        (planned.sku_id, planned.region): draw(st.floats(-10.0, 500.0)) for planned in lines
    }
    return PromoPlan(lines=lines), demand, available


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(case=small_plans(), seed=st.integers(0, 2**32 - 1))
def test_p10_p50_p90_are_ordered_for_every_metric(
    case: tuple[PromoPlan, HandBuilt, dict[tuple[str, Region], float]], seed: int
) -> None:
    plan, demand, available = case

    result = run(plan, inputs(demand, available), n_runs=200, seed=seed)

    for outcomes in [*result.lines, result.total]:
        ranges = [
            outcomes.units,
            outcomes.revenue,
            outcomes.gross_profit,
            outcomes.margin,
            outcomes.promo_spend,
        ]
        if outcomes.sell_through is not None:
            ranges.append(outcomes.sell_through)
        for metric in ranges:
            assert metric.p10 <= metric.p50 <= metric.p90
    for simulated in result.lines:
        assert 0.0 <= simulated.stockout_probability <= 1.0
        assert simulated.units.p90 <= max(available[(simulated.sku_id, simulated.region)], 0.0)


def test_a_simulation_needs_at_least_one_run() -> None:
    with pytest.raises(ValueError, match="n_runs"):
        run(PromoPlan(lines=(line("A"),)), inputs(NOISY), n_runs=0)
