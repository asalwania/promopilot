import numpy as np
import pytest

from promopilot.domain import CompanyPolicy, Mechanism, Segment, TargetSegment
from promopilot.economics import (
    blended_margin,
    clearance_value,
    discount_funding,
    effective_unit_price,
    fixed_marketing_cost,
    gross_profit,
    incremental_profit,
    margin,
    promo_cost,
)

UNITS_BY_SEGMENT = {
    Segment.VALUE_SEEKERS: 200.0,
    Segment.FAMILIES: 150.0,
    Segment.PREMIUM: 50.0,
    Segment.YOUNG_URBAN: 100.0,
}


@pytest.mark.parametrize(
    ("mechanism", "base_price", "depth_pct", "expected"),
    [
        (Mechanism.PCT_OFF, 200.0, 15, 170.0),
        (Mechanism.PCT_OFF, 49.0, 50, 24.5),
        (Mechanism.BOGO, 80.0, 50, 40.0),
        # Charm price: the largest whole-rupee price ending in 9 at or below the depth price.
        (Mechanism.FIXED_PRICE, 110.0, 10, 99.0),
        (Mechanism.FIXED_PRICE, 250.0, 20, 199.0),
        (Mechanism.FIXED_PRICE, 100.0, 10, 89.0),
        (Mechanism.FIXED_PRICE, 45.0, 50, 19.0),
        (Mechanism.FIXED_PRICE, 330.0, 10, 289.0),
    ],
)
def test_effective_unit_price_per_mechanism(
    mechanism: Mechanism, base_price: float, depth_pct: int, expected: float
) -> None:
    assert effective_unit_price(mechanism, base_price, depth_pct) == pytest.approx(expected)


def test_bundle_discount_is_split_between_the_pair_pro_rata_by_base_price() -> None:
    # Pair ₹60 + ₹40 at 20% off the pair price: ₹20 off, split 60:40 → ₹12 and ₹8.
    anchor = effective_unit_price(Mechanism.BUNDLE, 60.0, 20)
    partner = effective_unit_price(Mechanism.BUNDLE, 40.0, 20)

    assert (anchor, partner) == pytest.approx((48.0, 32.0))
    assert anchor + partner == pytest.approx(80.0)


def test_effective_unit_price_works_elementwise_on_arrays() -> None:
    prices = effective_unit_price(Mechanism.FIXED_PRICE, np.array([110.0, 250.0]), 10)

    np.testing.assert_allclose(prices, [99.0, 219.0])


def test_fixed_price_below_the_lowest_charm_price_is_rejected() -> None:
    with pytest.raises(ValueError, match="charm price"):
        effective_unit_price(Mechanism.FIXED_PRICE, 12.0, 50)


def test_discount_funding_for_all_customers_counts_every_segment_s_units() -> None:
    # ₹100 → ₹80 on 200 + 150 + 50 + 100 = 500 units: ₹20 x 500.
    funding = discount_funding(100.0, 80.0, UNITS_BY_SEGMENT, TargetSegment.ALL_CUSTOMERS)

    assert funding == pytest.approx(10_000.0)


def test_discount_funding_for_a_segment_exclusive_offer_counts_only_that_segment() -> None:
    # Families only: ₹20 x 150 units.
    funding = discount_funding(100.0, 80.0, UNITS_BY_SEGMENT, TargetSegment.FAMILIES)

    assert funding == pytest.approx(3_000.0)


def test_fixed_marketing_cost_is_charged_per_line_week_by_mechanism() -> None:
    policy = CompanyPolicy()

    assert fixed_marketing_cost(Mechanism.PCT_OFF, 2, policy) == pytest.approx(4_000.0)
    assert fixed_marketing_cost(Mechanism.BOGO, 3, policy) == pytest.approx(9_000.0)
    assert fixed_marketing_cost(Mechanism.BUNDLE, 1, policy) == pytest.approx(4_000.0)


def test_promo_cost_is_discount_funding_plus_fixed_marketing_cost() -> None:
    # BUNDLE ₹60 + ₹40 at 20% for Families only, 2 weeks:
    # anchor ₹12 x 150 = ₹1,800; partner ₹8 x 120 = ₹960; fixed ₹4,000 x 2 = ₹8,000.
    anchor_units = {**UNITS_BY_SEGMENT}
    partner_units = {segment: 0.8 * units for segment, units in UNITS_BY_SEGMENT.items()}
    funding = discount_funding(60.0, 48.0, anchor_units, TargetSegment.FAMILIES) + discount_funding(
        40.0, 32.0, partner_units, TargetSegment.FAMILIES
    )

    cost = promo_cost(funding, Mechanism.BUNDLE, 2, CompanyPolicy())

    assert cost == pytest.approx(10_760.0)


def test_discount_funding_works_elementwise_on_arrays() -> None:
    units = {segment: np.array([units, 2 * units]) for segment, units in UNITS_BY_SEGMENT.items()}

    funding = discount_funding(100.0, 80.0, units, TargetSegment.PREMIUM)

    np.testing.assert_allclose(funding, [1_000.0, 2_000.0])


def test_margin_is_price_minus_cost_over_price() -> None:
    assert margin(80.0, 60.0) == pytest.approx(0.25)
    assert margin(50.0, 60.0) == pytest.approx(-0.20)


def test_gross_profit_is_units_times_unit_margin() -> None:
    assert gross_profit(500.0, 80.0, 60.0) == pytest.approx(10_000.0)


def test_blended_margin_weights_plan_lines_by_revenue() -> None:
    # ₹40,000 revenue at 25% and ₹20,000 at 10%: ₹12,000 / ₹60,000.
    assert blended_margin([40_000.0, 20_000.0], [10_000.0, 2_000.0]) == pytest.approx(0.20)


def test_blended_margin_of_no_revenue_is_undefined() -> None:
    assert blended_margin([], []) is None


def test_clearance_value_counts_units_sold_beyond_baseline_at_the_write_off_rate() -> None:
    # 900 sold vs 400 baseline: 500 units x ₹60 cost x 30% write-off.
    assert clearance_value(900.0, 400.0, 60.0, 0.30) == pytest.approx(9_000.0)


def test_clearance_value_is_never_negative() -> None:
    assert clearance_value(300.0, 400.0, 60.0, 0.30) == 0.0


def test_incremental_profit_is_net_of_pull_forward_and_fixed_marketing_cost() -> None:
    # Base ₹100, cost ₹60, 2 promo weeks + 2 dip weeks, fixed cost ₹4,000.
    # Baseline: 400 units x ₹40 in the promo weeks + 400 x ₹40 after = ₹32,000.
    # 10% off: 800 units x ₹30 in the promo weeks + 350 x ₹40 in the dip = ₹38,000.
    baseline = gross_profit(400.0, 100.0, 60.0) + gross_profit(400.0, 100.0, 60.0)
    promoted = gross_profit(800.0, 90.0, 60.0) + gross_profit(350.0, 100.0, 60.0)

    assert incremental_profit(promoted, baseline, 4_000.0) == pytest.approx(2_000.0)


def test_incremental_profit_can_be_negative_when_the_dip_outweighs_the_uplift() -> None:
    # 20% off: 900 x ₹20 + a dip to 300 x ₹40 = ₹30,000 against the ₹32,000 baseline.
    promoted = gross_profit(900.0, 80.0, 60.0) + gross_profit(300.0, 100.0, 60.0)

    assert incremental_profit(promoted, 32_000.0, 4_000.0) == pytest.approx(-6_000.0)


def test_clearance_value_works_elementwise_on_arrays() -> None:
    value = clearance_value(np.array([900.0, 300.0]), np.array([400.0, 400.0]), 60.0, 0.30)

    np.testing.assert_allclose(value, [9_000.0, 0.0])
