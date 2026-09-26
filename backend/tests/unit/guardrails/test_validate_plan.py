"""`validate_plan` flags every hard constraint on hand-built plans (ADR 0012, ADR 0028)."""

from typing import Any

import pytest

from promopilot.domain import (
    CompanyPolicy,
    Mechanism,
    PlanLine,
    PlanningRequest,
    PromoWindow,
    Region,
    Scope,
    TargetSegment,
)
from promopilot.guardrails import (
    LineFacts,
    PlanFacts,
    SkuFacts,
    Violation,
    ViolationCode,
    validate_plan,
)

POLICY = CompanyPolicy()


def request(min_margin: float | None = 0.20, budget: float = 100_000.0) -> PlanningRequest:
    return PlanningRequest(
        as_of_week=100,
        scope=Scope(regions=(Region.NORTH, Region.WEST), categories=("Snacks", "Beverages")),
        promo_window=PromoWindow(start_week=101, end_week=104),
        marketing_budget=budget,
        min_margin=min_margin,
    )


def sku(
    category: str = "Snacks",
    base_price: float = 100.0,
    unit_cost: float = 60.0,
    overstocked: bool = False,
) -> SkuFacts:
    return SkuFacts(
        category=category, base_price=base_price, unit_cost=unit_cost, overstocked=overstocked
    )


def fact(
    sku_id: str = "S1",
    region: Region = Region.NORTH,
    mechanism: Mechanism = Mechanism.PCT_OFF,
    depth_pct: int = 20,
    start_week: int = 101,
    duration_weeks: int = 2,
    partner_sku_id: str | None = None,
    anchor: SkuFacts | None = None,
    partner: SkuFacts | None = None,
    **numbers: Any,
) -> LineFacts:
    """A plan line at a 25% margin that satisfies every constraint unless told otherwise."""
    values: dict[str, Any] = {
        "expected_units": 1_000.0,
        "p90_units": 1_300.0,
        "available_stock": 2_000.0,
        "expected_revenue": 80_000.0,
        "expected_gross_profit": 20_000.0,
        "promo_cost": 24_000.0,
    }
    values.update(numbers)
    line = PlanLine(
        sku_id=sku_id,
        region=region,
        mechanism=mechanism,
        depth_pct=depth_pct,
        duration_weeks=duration_weeks,
        start_week=start_week,
        target_segment=TargetSegment.ALL_CUSTOMERS,
        bundle_partner_sku_id=partner_sku_id,
    )
    return LineFacts(line=line, anchor=anchor or sku(), partner=partner, **values)


def codes(violations: tuple[Violation, ...]) -> list[ViolationCode]:
    return [violation.code for violation in violations]


def test_a_plan_inside_every_constraint_has_no_violations() -> None:
    plan = PlanFacts(
        lines=(
            fact("S1", Region.NORTH),
            fact("S2", Region.WEST, anchor=sku("Beverages"), start_week=103),
            fact(
                "S3",
                Region.NORTH,
                Mechanism.BUNDLE,
                partner_sku_id="S4",
                partner=sku(base_price=50.0, unit_cost=30.0),
            ),
        )
    )

    assert validate_plan(plan, request(), POLICY) == ()


def test_an_empty_plan_has_no_violations() -> None:
    assert validate_plan(PlanFacts(lines=()), request(), POLICY) == ()


def test_total_promo_cost_over_the_marketing_budget_is_flagged() -> None:
    plan = PlanFacts(lines=(fact("S1", promo_cost=60_000.0), fact("S2", promo_cost=40_000.02)))

    (violation,) = validate_plan(plan, request(budget=100_000.0), POLICY)

    assert violation.code is ViolationCode.BUDGET
    assert violation.actual == pytest.approx(100_000.02)
    assert violation.limit == 100_000.0


def test_the_budget_allows_one_paisa_of_float_error() -> None:
    plan = PlanFacts(lines=(fact("S1", promo_cost=60_000.0), fact("S2", promo_cost=40_000.01)))

    assert validate_plan(plan, request(budget=100_000.0), POLICY) == ()


def test_blended_margin_under_the_minimum_margin_is_flagged() -> None:
    # 18% blended margin: above the 15% margin floor, below the brief's 20%.
    plan = PlanFacts(lines=(fact(expected_revenue=80_000.0, expected_gross_profit=14_400.0),))

    (violation,) = validate_plan(plan, request(min_margin=0.20), POLICY)

    assert violation.code is ViolationCode.MIN_MARGIN
    assert violation.actual == pytest.approx(0.18)
    assert violation.limit == 0.20


def test_blended_margin_is_revenue_weighted_across_lines() -> None:
    # 30% on ₹80,000 and 5% on ₹20,000 blend to 25%: no violation although one line is low.
    plan = PlanFacts(
        lines=(
            fact("S1", expected_revenue=80_000.0, expected_gross_profit=24_000.0),
            fact("S2", expected_revenue=20_000.0, expected_gross_profit=1_000.0),
        )
    )

    assert validate_plan(plan, request(min_margin=0.20), POLICY) == ()


def test_blended_margin_under_the_margin_floor_is_flagged_even_without_a_minimum_margin() -> None:
    plan = PlanFacts(lines=(fact(expected_revenue=80_000.0, expected_gross_profit=11_200.0),))

    (violation,) = validate_plan(plan, request(min_margin=None), POLICY)

    assert violation.code is ViolationCode.MARGIN_FLOOR
    assert violation.actual == pytest.approx(0.14)
    assert violation.limit == POLICY.margin_floor


def test_blended_margin_under_both_minimum_margin_and_floor_flags_both() -> None:
    plan = PlanFacts(lines=(fact(expected_revenue=80_000.0, expected_gross_profit=11_200.0),))

    assert codes(validate_plan(plan, request(min_margin=0.20), POLICY)) == [
        ViolationCode.MIN_MARGIN,
        ViolationCode.MARGIN_FLOOR,
    ]


def test_p90_units_above_available_stock_are_flagged_per_line() -> None:
    plan = PlanFacts(lines=(fact("S1"), fact("S2", p90_units=2_100.0, available_stock=2_000.0)))

    (violation,) = validate_plan(plan, request(), POLICY)

    assert violation.code is ViolationCode.STOCK
    assert (violation.sku_id, violation.region) == ("S2", Region.NORTH)
    assert (violation.actual, violation.limit) == (2_100.0, 2_000.0)


def test_a_depth_over_the_maximum_discount_is_flagged() -> None:
    policy = CompanyPolicy(max_discount_pct=30)
    plan = PlanFacts(lines=(fact(depth_pct=40),))

    (violation,) = validate_plan(plan, request(), policy)

    assert violation.code is ViolationCode.MAX_DISCOUNT
    assert violation.actual == pytest.approx(0.40)
    assert violation.limit == pytest.approx(0.30)


def test_a_charm_price_deeper_than_the_maximum_discount_is_flagged() -> None:
    # 25% off ₹100 is ₹75; the charm price is ₹69, an effective 31% off (ADR 0015).
    policy = CompanyPolicy(max_discount_pct=30)
    plan = PlanFacts(lines=(fact(mechanism=Mechanism.FIXED_PRICE, depth_pct=25),))

    (violation,) = validate_plan(plan, request(), policy)

    assert violation.code is ViolationCode.MAX_DISCOUNT
    assert violation.actual == pytest.approx(0.31)


def test_bogo_is_an_effective_half_price() -> None:
    policy = CompanyPolicy(max_discount_pct=40)
    plan = PlanFacts(
        lines=(
            fact(
                mechanism=Mechanism.BOGO,
                depth_pct=50,
                anchor=sku(unit_cost=40),
            ),
        )
    )

    assert codes(validate_plan(plan, request(), policy)) == [ViolationCode.MAX_DISCOUNT]


def test_a_line_priced_below_unit_cost_is_flagged() -> None:
    # 50% off ₹100 is ₹50, under the ₹60 unit cost.
    plan = PlanFacts(lines=(fact(depth_pct=50),))

    (violation,) = validate_plan(plan, request(), POLICY)

    assert violation.code is ViolationCode.BELOW_COST
    assert (violation.sku_id, violation.actual, violation.limit) == ("S1", 50.0, 60.0)


def test_an_overstocked_sku_may_sell_below_unit_cost() -> None:
    plan = PlanFacts(lines=(fact(depth_pct=50, anchor=sku(overstocked=True)),))

    assert validate_plan(plan, request(), POLICY) == ()


def test_a_bundle_partner_priced_below_its_unit_cost_is_flagged() -> None:
    plan = PlanFacts(
        lines=(
            fact(
                "S1",
                mechanism=Mechanism.BUNDLE,
                partner_sku_id="S2",
                partner=sku(base_price=50.0, unit_cost=45.0),
            ),
        )
    )

    (violation,) = validate_plan(plan, request(), POLICY)

    assert violation.code is ViolationCode.BELOW_COST
    assert (violation.sku_id, violation.actual, violation.limit) == ("S2", 40.0, 45.0)


@pytest.mark.parametrize(
    ("start_week", "duration_weeks"),
    [
        (100, 1),  # starts before the window
        (104, 2),  # ends after the window
    ],
)
def test_a_line_outside_the_promo_window_is_flagged(start_week: int, duration_weeks: int) -> None:
    plan = PlanFacts(lines=(fact(start_week=start_week, duration_weeks=duration_weeks),))

    (violation,) = validate_plan(plan, request(), POLICY)

    assert violation.code is ViolationCode.WINDOW
    assert violation.sku_id == "S1"


def test_more_promoted_skus_per_category_per_region_than_policy_allows_is_flagged() -> None:
    policy = CompanyPolicy(max_promoted_skus_per_category_per_region=2)
    plan = PlanFacts(
        lines=(
            fact("S1"),
            fact("S2"),
            fact("S3"),
            fact("S4", Region.WEST),
            fact("S5", anchor=sku("Beverages")),
        )
    )

    (violation,) = validate_plan(plan, request(budget=1_000_000.0), policy)

    assert violation.code is ViolationCode.MAX_SKUS
    assert violation.region is Region.NORTH
    assert (violation.actual, violation.limit) == (3, 2)
    assert "Snacks" in violation.message


def test_a_bundle_partner_counts_toward_max_promoted_skus() -> None:
    policy = CompanyPolicy(max_promoted_skus_per_category_per_region=2)
    plan = PlanFacts(
        lines=(
            fact("S1"),
            fact("S2", mechanism=Mechanism.BUNDLE, partner_sku_id="S3", partner=sku()),
        )
    )

    assert codes(validate_plan(plan, request(), policy)) == [ViolationCode.MAX_SKUS]


def test_two_lines_for_one_sku_in_one_region_are_flagged() -> None:
    plan = PlanFacts(lines=(fact("S1"), fact("S1", start_week=103), fact("S1", Region.WEST)))

    (violation,) = validate_plan(plan, request(), POLICY)

    assert violation.code is ViolationCode.DUPLICATE_LINE
    assert (violation.sku_id, violation.region) == ("S1", Region.NORTH)


def test_a_bundle_partner_occupies_its_region() -> None:
    plan = PlanFacts(
        lines=(
            fact("S1", mechanism=Mechanism.BUNDLE, partner_sku_id="S2", partner=sku()),
            fact("S2"),
        )
    )

    assert codes(validate_plan(plan, request(), POLICY)) == [ViolationCode.DUPLICATE_LINE]


def test_violations_carry_a_readable_message() -> None:
    plan = PlanFacts(lines=(fact(promo_cost=150_000.0),))

    (violation,) = validate_plan(plan, request(budget=100_000.0), POLICY)

    assert "₹1,50,000" in violation.message
    assert "₹1,00,000" in violation.message


def test_line_facts_need_partner_facts_exactly_for_a_bundle() -> None:
    with pytest.raises(ValueError, match="partner"):
        fact(mechanism=Mechanism.BUNDLE, partner_sku_id="S2", partner=None)
    with pytest.raises(ValueError, match="partner"):
        fact(partner=sku())


def test_violations_are_immutable() -> None:
    plan = PlanFacts(lines=(fact(depth_pct=50),))
    (violation,) = validate_plan(plan, request(), POLICY)

    with pytest.raises(ValueError, match="frozen"):
        violation.code = ViolationCode.BUDGET  # type: ignore[misc]
