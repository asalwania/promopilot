"""The safety margin's arithmetic (ADR 0080): how each plan line's promo cost, units and
margin count against the budget, its stock and the minimum margin."""

import numpy as np
import pytest
from pydantic import ValidationError

from promopilot.domain import P90_Z, SafetyMargin
from promopilot.guardrails import (
    margin_shortfall,
    planned_margin,
    planned_promo_cost,
    promo_cost_std,
    stock_units,
)

MARGIN = SafetyMargin(budget_quantile=0.9, stock_sigmas=2.0, margin_quantile=0.1)


def test_the_default_margin_plans_on_expected_values_and_p90_units() -> None:
    none = SafetyMargin()
    assert planned_promo_cost(np.array([1_000.0]), np.array([200.0]), none) == pytest.approx(
        [1_000.0]
    )
    assert stock_units(np.array([100.0]), np.array([10.0]), none) == pytest.approx(
        [100.0 + P90_Z * 10.0]
    )
    shortfall = margin_shortfall(
        np.array([100.0]), np.array([10.0]), np.array([0.1]), minimum=0.2, margin=none
    )
    assert shortfall == pytest.approx([10.0])


@pytest.mark.parametrize(
    "fields",
    [
        {"budget_quantile": 0.4},
        {"budget_quantile": 1.0},
        {"stock_sigmas": 1.0},
        {"margin_quantile": 0.6},
        {"margin_quantile": 0.0},
    ],
)
def test_a_margin_that_would_plan_below_expectation_is_refused(fields: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        SafetyMargin.model_validate(fields)


def test_the_promo_cost_counts_at_its_budget_quantile() -> None:
    cost = planned_promo_cost(np.array([1_000.0, 500.0]), np.array([200.0, 0.0]), MARGIN)
    assert cost == pytest.approx([1_000.0 + P90_Z * 200.0, 500.0], rel=1e-4)


def test_the_promo_cost_std_scales_each_skus_discount_funding_by_its_units_cv() -> None:
    std = promo_cost_std(
        anchor_funding=np.array([1_000.0, 1_000.0]),
        units=np.array([100.0, 0.0]),
        units_std=np.array([10.0, 5.0]),
        partner_funding=np.array([500.0, 0.0]),
        partner_units=np.array([50.0, 0.0]),
        partner_units_std=np.array([10.0, 0.0]),
    )
    # 1,000 x 10% + 500 x 20%; a line with no units has no spread to scale.
    assert std == pytest.approx([200.0, 0.0])


def test_stock_holds_the_expected_units_plus_the_buffer() -> None:
    assert stock_units(np.array([100.0]), np.array([10.0]), MARGIN) == pytest.approx([120.0])


def test_the_margin_counts_each_lines_units_on_the_side_that_lowers_the_blend() -> None:
    shortfall = margin_shortfall(
        revenue=np.array([100.0, 100.0]),
        gross_profit=np.array([10.0, 30.0]),
        units_cv=np.array([0.1, 0.1]),
        minimum=0.2,
        margin=MARGIN,
    )
    # A line below the minimum sells more at its P90; one above it sells less at its P10.
    assert shortfall == pytest.approx([10.0 * (1 + P90_Z * 0.1), -10.0 * (1 - P90_Z * 0.1)], 1e-4)


def test_units_never_fall_below_zero_on_the_low_side() -> None:
    shortfall = margin_shortfall(
        np.array([100.0]), np.array([30.0]), np.array([2.0]), minimum=0.2, margin=MARGIN
    )
    assert shortfall == pytest.approx([0.0])


def test_the_planned_margin_is_the_least_blend_within_the_quantiles() -> None:
    revenue, profit, cv = np.array([100.0, 100.0]), np.array([10.0, 30.0]), np.array([0.1, 0.1])
    high, low = 1 + P90_Z * 0.1, 1 - P90_Z * 0.1
    margin = planned_margin(revenue, profit, cv, MARGIN)
    assert margin == pytest.approx((10 * high + 30 * low) / (100 * high + 100 * low), rel=1e-4)
    assert margin is not None
    # The minimum it keeps exactly: the margin row is zero there.
    at = margin_shortfall(revenue, profit, cv, minimum=margin, margin=MARGIN).sum()
    assert at == pytest.approx(0.0, abs=1e-6)
    assert planned_margin(revenue, profit, cv, SafetyMargin()) == pytest.approx(0.2)


def test_a_plan_with_no_revenue_has_no_margin() -> None:
    assert planned_margin(np.array([]), np.array([]), np.array([]), MARGIN) is None
