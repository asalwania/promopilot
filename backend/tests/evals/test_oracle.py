"""Oracle scoring on a tiny hand-written ground truth, checked against hand-computed values.

The world: one region (North), one store selling 100 units per segment per week (400 in
total) of each SKU at its base price. No seasonality, festivals or competitor effect.
- A: ₹100, cost ₹50, own-price elasticity -3, PCT_OFF effect +0.1.
- B: ₹50, cost ₹30, a substitute of A (theta_BA = 0.5).
- C: ₹40, cost ₹20, a complement of A (theta_CA = -0.4).
As-of week 10; a plan line runs from week 11. Fixed marketing cost is ₹2,000 per line-week
(POLICY), not the company default.
"""

from datetime import date
from math import log

import pandas as pd
import pytest

from promopilot.datagen import GeneratedDataset
from promopilot.datagen.truth import (
    CrossEffect,
    GroundTruth,
    HolidayWeek,
    SkuTruth,
    StoreTruth,
)
from promopilot.domain import (
    CompanyPolicy,
    Mechanism,
    PlanLine,
    PromoPlan,
    Region,
    Segment,
    TargetSegment,
)
from promopilot.evals import Oracle

WEEKS = 20
AS_OF = 10
POLICY = CompanyPolicy(fixed_cost_per_line_week=dict.fromkeys(Mechanism, 2_000.0))
"""The tiny world's hand-computed values assume ₹2,000 per line-week, whatever the default."""
PRICES = {"A": (100.0, 50.0), "B": (50.0, 30.0), "C": (40.0, 20.0)}


def sku(sku_id: str, *, beta: float = -2.0, pull_forward: float = 0.0) -> SkuTruth:
    return SkuTruth(
        sku_id=sku_id,
        category="Snacks" if sku_id != "C" else "Beverages",
        subcategory="Namkeen" if sku_id != "C" else "Soft Drinks",
        reference_price=PRICES[sku_id][0],
        base_level=log(400),
        season_amplitude=0.0,
        season_phase_week=0.0,
        elasticity=dict.fromkeys(Segment, beta),
        competitor_sensitivity=0.0,
        mechanism_effect={
            Mechanism.PCT_OFF: 0.1,
            Mechanism.FIXED_PRICE: 0.1,
            Mechanism.BOGO: 0.2,
            Mechanism.BUNDLE: 0.2,
        },
        pull_forward=pull_forward,
        dispersion=10.0,
    )


def tiny_oracle(
    *, pull_forward: float = 0.0, on_hand_a: int = 5_000, cover_a: float = 30.0
) -> Oracle:
    return Oracle(
        tiny_truth(pull_forward=pull_forward),
        tiny_products(),
        tiny_inventory(on_hand_a=on_hand_a, cover_a=cover_a),
    )


def tiny_truth(*, pull_forward: float = 0.0) -> GroundTruth:
    return GroundTruth(
        start_date=date(2024, 9, 30),
        history_weeks=AS_OF,
        horizon_weeks=WEEKS - AS_OF,
        pull_forward_window_weeks=4,
        skus=[sku("A", beta=-3.0, pull_forward=pull_forward), sku("B"), sku("C")],
        stores=[
            StoreTruth(
                store_id="N01",
                region=Region.NORTH,
                level=0.0,
                segment_mix=dict.fromkeys(Segment, 0.25),
            )
        ],
        segment_affinity={
            "Snacks": dict.fromkeys(Segment, 0.0),
            "Beverages": dict.fromkeys(Segment, 0.0),
        },
        holiday_sensitivity={"Snacks": {}, "Beverages": {}},
        holidays={Region.NORTH: [HolidayWeek(name=None, intensity=0.0)] * WEEKS},
        competitor_prices={Region.NORTH: {s: [PRICES[s][0]] * WEEKS for s in PRICES}},
        cross_effects=[
            CrossEffect(sku_id="B", other_sku_id="A", theta=0.5),
            CrossEffect(sku_id="C", other_sku_id="A", theta=-0.4),
        ],
        substitute_pairs=[("A", "B")],
        complement_pairs=[("A", "C")],
    )


def tiny_products() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "sku_id": list(PRICES),
            "category": ["Snacks", "Snacks", "Beverages"],
            "base_price": [p for p, _ in PRICES.values()],
            "unit_cost": [c for _, c in PRICES.values()],
        }
    )


def tiny_inventory(*, on_hand_a: int = 5_000, cover_a: float = 30.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "snapshot_week": AS_OF - 1,
            "store_id": "N01",
            "sku_id": list(PRICES),
            "on_hand": [on_hand_a, 5_000, 5_000],
            "safety_stock": [0, 0, 0],
            "days_of_cover": [cover_a, 30.0, 30.0],
        }
    )


def a_line(**changes: object) -> PlanLine:
    fields: dict[str, object] = {
        "sku_id": "A",
        "region": Region.NORTH,
        "mechanism": Mechanism.PCT_OFF,
        "depth_pct": 20,
        "duration_weeks": 1,
        "start_week": 11,
        "target_segment": TargetSegment.ALL_CUSTOMERS,
    }
    return PlanLine.model_validate(fields | changes)


def test_a_single_pct_off_line_scores_its_true_expected_outcome() -> None:
    # 400 x 0.8^-3 x e^0.1 = 863.41 units at ₹80 (₹30 margin) against 400 x ₹50 baseline.
    result = tiny_oracle().evaluate(PromoPlan(lines=(a_line(),)), AS_OF, POLICY)
    line = result.lines[0]

    assert line.units == pytest.approx(863.41, abs=0.01)
    assert line.baseline_units == pytest.approx(400.0)
    assert line.revenue == pytest.approx(69_073.18, abs=0.01)
    assert line.gross_profit == pytest.approx(25_902.44, abs=0.01)
    assert line.incremental_profit == pytest.approx(3_902.44, abs=0.01)  # minus ₹2,000 fixed
    assert line.promo_cost == pytest.approx(19_268.30, abs=0.01)  # ₹20 x 863.41 + ₹2,000
    assert line.stock_capped is False
    assert line.sell_through == pytest.approx(863.41 / 5_000, abs=1e-5)


def test_pull_forward_dips_the_weeks_after_a_promotion_and_is_netted_off() -> None:
    # phi = 0.4 over a 4-week window, 2-week promotion:
    # week 2 of the promo dips by e^(-0.4 x 1/4): 863.41 -> 781.25 units;
    # the 4 weeks after lose 400 x [3 x (1 - e^-0.2) + (1 - e^-0.1)] = 255.59 units.
    line = a_line(duration_weeks=2)
    result = tiny_oracle(pull_forward=0.4).evaluate(PromoPlan(lines=(line,)), AS_OF, POLICY)
    outcome = result.lines[0]

    assert outcome.units == pytest.approx(863.41 + 781.25, abs=0.01)
    assert outcome.pull_forward_units == pytest.approx(255.59, abs=0.01)
    # (1,644.66 x ₹30) - (800 x ₹50) - (255.59 x ₹50) - ₹4,000 fixed
    assert outcome.incremental_profit == pytest.approx(-7_439.46, abs=0.01)


def test_units_are_capped_at_available_stock_and_the_cap_is_reported() -> None:
    # Only 500 units in stock: sells 500 at ₹30 margin instead of 863.41.
    result = tiny_oracle(on_hand_a=500).evaluate(PromoPlan(lines=(a_line(),)), AS_OF, POLICY)
    line = result.lines[0]

    assert line.stock_capped is True
    assert line.units == pytest.approx(500.0)
    assert line.incremental_profit == pytest.approx(15_000 - 20_000 - 2_000)
    assert line.promo_cost == pytest.approx(20 * 500 + 2_000)
    assert line.sell_through == pytest.approx(1.0)
    assert result.stock_capped_lines == 1


def test_promoting_a_takes_profit_from_its_out_of_scope_substitute() -> None:
    # B sells 400 x 0.8^0.5 = 357.77 instead of 400: 42.23 units x ₹20 margin lost.
    result = tiny_oracle().evaluate(PromoPlan(lines=(a_line(),)), AS_OF, POLICY)

    assert result.lines[0].cannibalisation == pytest.approx(844.58, abs=0.01)
    assert result.cannibalisation == pytest.approx(844.58, abs=0.01)


def test_promoting_a_adds_halo_profit_on_its_complement() -> None:
    # C sells 400 x 0.8^-0.4 = 437.35 instead of 400: 37.35 units x ₹20 margin gained.
    result = tiny_oracle().evaluate(PromoPlan(lines=(a_line(),)), AS_OF, POLICY)

    assert result.lines[0].halo == pytest.approx(746.90, abs=0.01)
    assert result.halo == pytest.approx(746.90, abs=0.01)


def test_plan_totals_net_cannibalisation_and_include_halo() -> None:
    result = tiny_oracle().evaluate(PromoPlan(lines=(a_line(),)), AS_OF, POLICY)

    assert result.incremental_profit == pytest.approx(3_902.44 - 844.58 + 746.90, abs=0.02)
    assert result.promo_cost == pytest.approx(19_268.30, abs=0.01)
    assert result.blended_margin == pytest.approx(30 / 80)
    assert result.objective == pytest.approx(result.incremental_profit + result.clearance_value)


def test_selling_an_overstocked_sku_beyond_baseline_earns_clearance_value() -> None:
    # A has 100 days of cover (> 8 weeks): (863.41 - 400) x ₹50 cost x 30% write-off.
    result = tiny_oracle(cover_a=100).evaluate(PromoPlan(lines=(a_line(),)), AS_OF, POLICY)

    assert result.lines[0].clearance_value == pytest.approx(6_951.22, abs=0.01)
    assert result.clearance_value == pytest.approx(6_951.22, abs=0.01)
    assert result.objective == pytest.approx(result.incremental_profit + 6_951.22, abs=0.01)


def test_a_sku_that_is_not_overstocked_earns_no_clearance_value() -> None:
    result = tiny_oracle().evaluate(PromoPlan(lines=(a_line(),)), AS_OF, POLICY)

    assert result.clearance_value == 0.0


def test_a_segment_exclusive_offer_funds_only_its_segment() -> None:
    # Families only: 100 x 0.8^-3 x e^0.1 = 215.85 promoted units + 300 at full price.
    line = a_line(target_segment=TargetSegment.FAMILIES)
    result = tiny_oracle().evaluate(PromoPlan(lines=(line,)), AS_OF, POLICY)
    outcome = result.lines[0]

    assert outcome.units == pytest.approx(215.85 + 300, abs=0.01)
    assert outcome.promo_cost == pytest.approx(6_317.07, abs=0.01)  # ₹20 x 215.854 + ₹2,000


def test_the_empty_plan_scores_zero() -> None:
    result = tiny_oracle().evaluate(PromoPlan(), AS_OF, POLICY)

    assert result.lines == ()
    assert result.incremental_profit == 0.0
    assert result.objective == 0.0
    assert result.promo_cost == 0.0
    assert result.blended_margin is None


def test_the_same_plan_always_gets_the_same_score() -> None:
    oracle = tiny_oracle(pull_forward=0.4)
    plan = PromoPlan(lines=(a_line(duration_weeks=3),))

    assert oracle.evaluate(plan, AS_OF, POLICY) == oracle.evaluate(plan, AS_OF, POLICY)


def test_a_plan_line_starting_before_the_as_of_week_is_rejected() -> None:
    with pytest.raises(ValueError, match="as-of week"):
        tiny_oracle().evaluate(PromoPlan(lines=(a_line(start_week=5),)), AS_OF, POLICY)


def test_the_oracle_scores_any_plan_on_a_generated_world(default_dataset: GeneratedDataset) -> None:
    oracle = Oracle.from_dataset(default_dataset)
    products = default_dataset.products
    bundle_pair = default_dataset.ground_truth.complement_pairs[0]
    plan = PromoPlan(
        lines=(
            PlanLine(
                sku_id=bundle_pair[0],
                region=Region.WEST,
                mechanism=Mechanism.BUNDLE,
                depth_pct=15,
                duration_weeks=2,
                start_week=108,
                target_segment=TargetSegment.ALL_CUSTOMERS,
                bundle_partner_sku_id=bundle_pair[1],
            ),
            PlanLine(
                sku_id=str(products["sku_id"].iloc[-1]),
                region=Region.NORTH,
                mechanism=Mechanism.FIXED_PRICE,
                depth_pct=10,
                duration_weeks=1,
                start_week=109,
                target_segment=TargetSegment.PREMIUM,
            ),
            PlanLine(
                sku_id=str(products["sku_id"].iloc[3]),
                region=Region.NORTH,
                mechanism=Mechanism.BOGO,
                depth_pct=50,
                duration_weeks=4,
                start_week=104,
                target_segment=TargetSegment.ALL_CUSTOMERS,
            ),
        )
    )

    result = oracle.evaluate(plan, 104, CompanyPolicy())

    assert len(result.lines) == 3
    assert all(line.units > 0 for line in result.lines)
    assert result.promo_cost > 0


def test_in_the_default_world_a_shallow_promotion_can_pay_without_clearing_stock(
    default_dataset: GeneratedDataset,
) -> None:
    """ADR 0037 (#109): net of pull-forward and the default fixed marketing cost, a one-week
    5% PCT_OFF in the demo brief's scope earns true incremental profit on some SKUs that
    clear no overstock, so a plan can hold more than clearance lines."""
    oracle = Oracle.from_dataset(default_dataset)
    products = default_dataset.products
    scoped = products.loc[products["category"].isin(["Snacks", "Beverages"]), "sku_id"]
    lines = [
        PlanLine(
            sku_id=str(sku_id),
            region=region,
            mechanism=Mechanism.PCT_OFF,
            depth_pct=5,
            duration_weeks=1,
            start_week=108,
            target_segment=TargetSegment.ALL_CUSTOMERS,
        )
        for sku_id in scoped
        for region in (Region.NORTH, Region.WEST)
    ]

    outcomes = [
        oracle.evaluate(PromoPlan(lines=(line,)), 104, CompanyPolicy()).lines[0] for line in lines
    ]

    paying = [o for o in outcomes if o.incremental_profit > 0 and o.clearance_value == 0]
    assert len(paying) >= 10
