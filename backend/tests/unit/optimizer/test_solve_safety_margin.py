"""The optimiser plans with a safety margin (ADR 0080): each option's promo cost counts at its
P90 against the budget, its expected units plus a buffer of standard deviations must fit its
stock, and the blended margin must reach the minimum with units at their P10. The margin
enters as the constraint rows' coefficients, so the model is no larger.

When the budget margin alone puts a clearance target out of reach, the request is planned at
the expected promo cost instead, and the result says so.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import NormalDist

import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from promopilot.domain import (
    P90_Z,
    ClearanceTarget,
    CompanyPolicy,
    ConstraintKind,
    NotSelectedReason,
    Region,
    SafetyMargin,
    SolveStatus,
)
from promopilot.guardrails import validate_plan
from promopilot.optimizer import (
    ClearanceBaseline,
    OptimisationResult,
    PromoOptions,
    SolverSettings,
    plan_facts,
    solve,
)
from tests.unit.optimizer.test_solve import SEED, FakeFacts, Row, line, options_of, request

MARGIN = SolverSettings(budget_quantile=0.9, stock_buffer_sigmas=2.0, margin_quantile=0.1)
Z90 = NormalDist().inv_cdf(0.9)
"""Promo cost at its P90 is expected + Z90 std."""
NONE = SolverSettings(budget_quantile=0.5, stock_buffer_sigmas=P90_Z, margin_quantile=0.5)


@dataclass(frozen=True)
class Spread:
    """An option's expected units, their std, and the discount funding that moves with them."""

    units: float = 80.0
    units_std: float = 0.0
    funding: float = 0.0


def options_with(
    rows: Sequence[Row],
    spreads: Sequence[Spread],
    clearance: Sequence[ClearanceBaseline] = (),
) -> PromoOptions:
    options = options_of(rows, clearance)
    table: pd.DataFrame = options.table.copy()
    for n, spread in enumerate(spreads):
        table.loc[n, "units"] = spread.units
        table.loc[n, "units_std"] = spread.units_std
        table.loc[n, "anchor_discount_funding"] = spread.funding
        table.loc[n, "p90_units"] = spread.units + P90_Z * spread.units_std
    return PromoOptions(
        lines=options.lines,
        table=table,
        enumerated=options.enumerated,
        pruned=options.pruned,
        clearance=options.clearance,
    )


def solved(
    rows: Sequence[Row],
    spreads: Sequence[Spread],
    solver: SolverSettings,
    *,
    clearance: Sequence[ClearanceBaseline] = (),
    **brief: object,
) -> tuple[PromoOptions, OptimisationResult]:
    options = options_with(rows, spreads, clearance)
    result = solve(
        request(**brief),  # type: ignore[arg-type]
        options,
        FakeFacts(),
        CompanyPolicy(),
        settings=solver,
        seed=SEED,
    )
    return options, result


def skus(result: OptimisationResult) -> list[str]:
    return sorted(plan_line.sku_id for plan_line in result.plan.lines)


def test_each_options_promo_cost_counts_at_its_p90_against_the_budget() -> None:
    # A costs 1,000 expected; its 800 of funding moves with a 25% cv: std 200, P90 ~1,256.
    rows = [
        Row(line("A"), value=600.0, promo_cost=1_000.0),
        Row(line("B"), value=500.0, promo_cost=1_000.0),
    ]
    spreads = [Spread(units=100.0, units_std=25.0, funding=800.0), Spread()]

    _, planned = solved(rows, spreads, NONE, budget=2_100.0)
    _, safe = solved(rows, spreads, MARGIN, budget=2_100.0)

    assert skus(planned) == ["A", "B"]
    assert skus(safe) == ["A"]
    assert safe.safety_margin.planned_promo_cost == round(1_000.0 + Z90 * 200.0, 2)
    assert planned.safety_margin.planned_promo_cost == 2_000.0
    assert safe.safety_margin.budget_quantile == 0.9
    assert not safe.safety_margin.budget_margin_waived


def test_a_regional_cap_counts_promo_cost_at_its_p90_too() -> None:
    rows = [Row(line("A"), value=600.0, promo_cost=1_000.0)]
    spreads = [Spread(units=100.0, units_std=25.0, funding=800.0)]

    _, capped = solved(rows, spreads, MARGIN, regional_budget_caps={Region.NORTH: 1_200.0})

    assert skus(capped) == []


def test_expected_units_must_leave_the_stock_buffer() -> None:
    # 100 units with std 10: P90 ~113 fits 115 in stock, but 100 + 2 x 10 = 120 does not.
    rows = [Row(line("A"), value=600.0, available_stock=115.0)]
    spreads = [Spread(units=100.0, units_std=10.0)]

    _, planned = solved(rows, spreads, NONE)
    _, safe = solved(rows, spreads, MARGIN)

    assert skus(planned) == ["A"]
    assert skus(safe) == []
    (left_out,) = safe.not_selected
    assert NotSelectedReason.OUT_OF_STOCK in left_out.reasons


def test_the_minimum_margin_holds_with_units_at_their_p10() -> None:
    # 20% and 30% lines blend to 25%, but not at their P10 (the 20% line sells more).
    rows = [
        Row(line("A"), value=600.0, revenue=10_000.0, gross_profit=2_000.0),
        Row(line("C"), value=500.0, revenue=10_000.0, gross_profit=3_000.0),
    ]
    spreads = [Spread(units=100.0, units_std=10.0), Spread(units=100.0, units_std=10.0)]

    _, planned = solved(rows, spreads, NONE, min_margin=0.249)
    _, safe = solved(rows, spreads, MARGIN, min_margin=0.249)

    assert skus(planned) == ["A", "C"]
    assert skus(safe) == ["C"]


def test_every_plan_passes_validation_at_the_margin_it_was_planned_with() -> None:
    rows = [
        Row(line("A"), value=600.0, promo_cost=1_000.0, available_stock=125.0),
        Row(line("B"), value=500.0, promo_cost=900.0, revenue=10_000.0, gross_profit=1_000.0),
        Row(line("C"), value=400.0, promo_cost=700.0),
    ]
    spreads = [
        Spread(units=100.0, units_std=10.0, funding=800.0),
        Spread(units=100.0, units_std=20.0, funding=700.0),
        Spread(units=100.0, units_std=5.0, funding=500.0),
    ]
    options, safe = solved(rows, spreads, MARGIN, budget=2_000.0, min_margin=0.2)

    facts = plan_facts(options, safe.selected, FakeFacts(), safe.safety_margin)

    assert facts.safety == SafetyMargin(budget_quantile=0.9, stock_sigmas=2.0, margin_quantile=0.1)
    assert validate_plan(facts, request(budget=2_000.0, min_margin=0.2), CompanyPolicy()) == ()


spread = st.builds(
    Spread,
    units=st.floats(10, 200),
    units_std=st.floats(0, 40),
    funding=st.floats(0, 900),
)
row = st.builds(
    lambda sku, value, cost, profit, stock: Row(
        line(sku), value=value, promo_cost=cost, gross_profit=profit, available_stock=stock
    ),
    st.sampled_from(["A", "B", "C", "D"]),
    st.floats(1, 1_000),
    st.floats(1_000, 2_000),
    st.floats(500, 4_000),
    st.floats(50, 400),
)


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    st.lists(st.tuples(row, spread), min_size=1, max_size=6),
    st.floats(1_000, 8_000),
    st.sampled_from([None, 0.2, 0.3]),
)
def test_any_plan_keeps_its_p90_budget_stock_buffer_and_p10_margin(
    pairs: list[tuple[Row, Spread]], budget: float, min_margin: float | None
) -> None:
    rows, spreads = [r for r, _ in pairs], [s for _, s in pairs]
    options, result = solved(rows, spreads, MARGIN, budget=budget, min_margin=min_margin)

    facts = plan_facts(options, result.selected, FakeFacts(), result.safety_margin)
    brief = request(budget=budget, min_margin=min_margin)
    assert validate_plan(facts, brief, CompanyPolicy()) == ()
    assert result.safety_margin.planned_promo_cost <= budget + 0.01


# ---------------------------------------------------------------- clearance targets (D4)

TARGET = ClearanceBaseline(
    sku_id="A", region=Region.NORTH, available_stock=1_000.0, baseline_units=100.0
)


def test_the_budget_margin_gives_way_when_a_clearance_target_needs_the_whole_budget() -> None:
    # Only the A line reaches the 50% target (400 units more), and it costs the whole budget.
    rows = [Row(line("A"), value=-50.0, promo_cost=1_000.0, window_uplift=450.0)]
    spreads = [Spread(units=500.0, units_std=50.0, funding=900.0)]
    brief = {
        "budget": 1_000.0,
        "clearance_targets": (ClearanceTarget(sku_id="A", sell_through=0.5),),
    }

    options, result = solved(rows, spreads, MARGIN, clearance=[TARGET], **brief)

    assert result.status is SolveStatus.OPTIMAL
    assert skus(result) == ["A"]
    waived = result.safety_margin
    assert waived.budget_margin_waived
    assert (waived.budget_quantile, waived.stock_sigmas, waived.margin_quantile) == (0.5, 2.0, 0.1)
    assert waived.planned_promo_cost == 1_000.0
    facts = plan_facts(options, result.selected, FakeFacts(), waived)
    assert validate_plan(facts, request(**brief), CompanyPolicy()) == ()  # type: ignore[arg-type]


def test_a_target_out_of_reach_even_at_the_expected_cost_keeps_the_margin() -> None:
    rows = [Row(line("A"), value=-50.0, promo_cost=1_000.0, window_uplift=450.0)]
    spreads = [Spread(units=500.0, units_std=50.0, funding=900.0)]
    brief = {"budget": 900.0, "clearance_targets": (ClearanceTarget(sku_id="A", sell_through=0.5),)}

    _, result = solved(rows, spreads, MARGIN, clearance=[TARGET], **brief)

    assert result.status is SolveStatus.INFEASIBLE
    assert not result.safety_margin.budget_margin_waived
    assert result.safety_margin.budget_quantile == 0.9
    assert result.relaxation is not None
    (budget,) = [c for c in result.relaxation.changes if c.kind is ConstraintKind.MARKETING_BUDGET]
    # Raising the budget is costed at the P90 promo cost the margin plans on.
    assert budget.relaxed == pytest.approx(1_000.0 + Z90 * 90.0, abs=0.01)


def test_settings_refuse_a_margin_below_expectation() -> None:
    for fields in (
        {"budget_quantile": 0.4},
        {"stock_buffer_sigmas": 1.0},
        {"margin_quantile": 0.7},
    ):
        try:
            SolverSettings(**fields)  # type: ignore[arg-type]
        except ValueError:
            continue
        raise AssertionError(f"{fields} was accepted")


def test_the_default_settings_plan_with_the_recommended_margin() -> None:
    assert SolverSettings().safety_margin == SafetyMargin(
        budget_quantile=0.9, stock_sigmas=2.0, margin_quantile=0.1
    )
