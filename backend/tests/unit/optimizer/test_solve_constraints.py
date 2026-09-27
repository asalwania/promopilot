"""The brief's optional constraints in the optimiser (SPEC §9.4, ADR 0040): clearance targets,
regional budget caps, the KVI price tolerance and a tighter promoted-SKU cap, on hand-computed
instances. Their hypothesis properties live with the others in `test_solve` and
`test_solve_reports`.
"""

from typing import Any

import pytest

from promopilot.domain import (
    BindingConstraint,
    BindingEvidence,
    ClearanceShortfall,
    CompanyPolicy,
    ConstraintKind,
    ConstraintSource,
    NotSelectedReason,
    Region,
    SelectionReason,
    SelectionReasonCode,
    SolveStatus,
)
from promopilot.guardrails import ClearanceFacts, ViolationCode, validate_plan
from promopilot.optimizer import ClearanceBaseline, OptimisationResult, SolverSettings, solve
from tests.unit.optimizer.test_solve import (
    SEED,
    FakeFacts,
    Row,
    line,
    options_of,
    plan_facts,
    request,
    run,
)
from tests.unit.optimizer.test_solve_reports import with_parts

# --- clearance targets -----------------------------------------------------------------------

D_NORTH = ClearanceBaseline(
    sku_id="D", region=Region.NORTH, available_stock=1_000.0, baseline_units=300.0
)
"""D sells 300 of its 1,000 units over the window unpromoted: a 50% target needs 200 more."""


def target(sell_through: float = 0.5, *sku_ids: str) -> list[dict[str, Any]]:
    return [{"sku_id": sku_id, "sell_through": sell_through} for sku_id in sku_ids or ("D",)]


def by_kind(result: OptimisationResult, kind: ConstraintKind) -> list[BindingConstraint]:
    return [c for c in result.binding_constraints if c.kind is kind]


D10 = line("D", depth_pct=10)
D20 = line("D", depth_pct=20)
D30 = line("D", depth_pct=30)
"""30% off D's ₹80 is ₹56, below its ₹60 unit cost: only an overstocked D may sell there."""


def test_a_clearance_sku_is_selected_for_its_clearance_value() -> None:
    options = with_parts(
        options_of([Row(D30, 0.0, window_uplift=250.0)], [D_NORTH]),
        0,
        incremental_profit=-50.0,
        clearance_value=200.0,
    )
    named = request(clearance_targets=target(0.2))

    result = solve(named, options, FakeFacts(), CompanyPolicy(), seed=SEED)

    # Named for clearance, D counts as overstocked and may sell below cost (ADR 0014).
    assert result.plan.lines == (D30,)
    (why,) = result.why_chosen
    assert SelectionReason(code=SelectionReasonCode.CLEARANCE_VALUE, amount=200.0) in why.reasons
    unnamed = solve(request(), options, FakeFacts(), CompanyPolicy(), seed=SEED)
    assert unnamed.plan.lines == ()


def test_a_clearance_target_is_met_even_by_a_line_that_loses_money() -> None:
    rows = [
        Row(D10, 100.0, window_uplift=100.0),
        Row(D30, -20.0, window_uplift=250.0),
    ]

    result = run(rows, clearance=[D_NORTH], clearance_targets=target())

    assert result.status is SolveStatus.OPTIMAL
    assert result.plan.lines == (D30,)
    assert result.objective == pytest.approx(-20.0)
    assert result.clearance_shortfalls == ()
    (why,) = result.why_chosen
    assert why.reasons == (
        SelectionReason(code=SelectionReasonCode.CLEARANCE_TARGET, amount=250.0),
    )
    assert by_kind(result, ConstraintKind.CLEARANCE_TARGET) == [
        BindingConstraint(
            kind=ConstraintKind.CLEARANCE_TARGET,
            source=ConstraintSource.BRIEF,
            limit=0.5,
            sku_id="D",
            region=Region.NORTH,
            evidence=BindingEvidence.EXACT,
            objective_gain=120.0,
        )
    ]


def test_an_unreachable_clearance_target_gives_the_closest_plan_and_reports_the_shortfall() -> None:
    rows = [Row(D10, 100.0, window_uplift=100.0)]

    result = run(rows, clearance=[D_NORTH], clearance_targets=target())

    # Infeasible (ADR 0044), but the closest plan still comes back.
    assert result.status is SolveStatus.INFEASIBLE
    assert result.plan.lines == (D10,)
    assert result.clearance_shortfalls == (
        ClearanceShortfall(
            sku_id="D",
            region=Region.NORTH,
            target=0.5,
            expected_sell_through=0.4,
            shortfall_units=100.0,
        ),
    )
    plan = plan_facts(rows, result.selected, FakeFacts()).model_copy(
        update={
            "clearance": (
                ClearanceFacts(
                    sku_id="D", region=Region.NORTH, available_stock=1_000.0, expected_units=400.0
                ),
            )
        }
    )
    violations = validate_plan(plan, request(clearance_targets=target()), CompanyPolicy())
    assert [v.code for v in violations] == [ViolationCode.CLEARANCE_TARGET]


def test_among_the_closest_plans_the_most_profitable_is_chosen() -> None:
    rows = [
        Row(D10, 10.0, window_uplift=150.0),
        Row(D20, 90.0, window_uplift=150.0),
    ]

    result = run(rows, clearance=[D_NORTH], clearance_targets=target())

    assert result.plan.lines == (D20,)
    assert [s.shortfall_units for s in result.clearance_shortfalls] == [pytest.approx(50.0)]


def test_a_budget_too_small_for_the_target_leaves_the_closest_affordable_plan() -> None:
    rows = [
        Row(D30, 50.0, promo_cost=2_000.0, window_uplift=250.0),
        Row(D10, 100.0, promo_cost=500.0, window_uplift=100.0),
    ]

    result = run(rows, clearance=[D_NORTH], clearance_targets=target(), budget=1_000.0)

    assert result.plan.lines == (D10,)
    assert [s.shortfall_units for s in result.clearance_shortfalls] == [pytest.approx(100.0)]


def test_the_shortfall_is_weighed_by_the_unit_cost_of_the_stock_left_short() -> None:
    a_north = ClearanceBaseline(
        sku_id="A", region=Region.NORTH, available_stock=1_000.0, baseline_units=400.0
    )
    d_north = ClearanceBaseline(
        sku_id="D", region=Region.NORTH, available_stock=1_000.0, baseline_units=400.0
    )
    rows = [
        Row(line("A", depth_pct=10), 500.0, promo_cost=1_000.0, window_uplift=100.0),
        Row(D10, 10.0, promo_cost=1_000.0, window_uplift=100.0),
    ]

    result = run(
        rows, clearance=[a_north, d_north], clearance_targets=target(0.5, "A", "D"), budget=1_000.0
    )

    # A unit of D's stock costs ₹60 and one of A's ₹40: D is cleared first.
    assert result.plan.lines == (D10,)
    assert [(s.sku_id, s.shortfall_units) for s in result.clearance_shortfalls] == [("A", 100.0)]


def test_a_clearance_target_applies_only_to_the_sku_the_brief_names() -> None:
    # B is overstocked by days of cover but not named: its line must pay for itself.
    facts = FakeFacts(overstocked={("B", Region.NORTH)})
    rows = [
        Row(line("B", depth_pct=50), -10.0, window_uplift=900.0),
        Row(D10, 100.0, window_uplift=250.0),
    ]

    result = run(rows, facts, clearance=[D_NORTH], clearance_targets=target())

    assert result.plan.lines == (D10,)
    assert result.clearance_shortfalls == ()


def test_no_plan_in_time_still_returns_a_plan_that_keeps_every_other_constraint() -> None:
    rows = [
        Row(line(sku_id, depth_pct=depth), float(depth), window_uplift=depth * 10.0)
        for sku_id in "ABD"
        for depth in (10, 20)
    ]
    tiny = SolverSettings(time_limit_seconds=1e-9, binding_time_limit_seconds=0)

    result = solve(
        request(clearance_targets=target()),
        options_of(rows, [D_NORTH]),
        FakeFacts(),
        CompanyPolicy(),
        settings=tiny,
        seed=SEED,
    )

    assert result.status in (SolveStatus.OPTIMAL, SolveStatus.FEASIBLE, SolveStatus.INFEASIBLE)
    plan = plan_facts(rows, result.selected, FakeFacts())
    others = [v for v in validate_plan(plan, request(clearance_targets=target()), CompanyPolicy())]
    assert others == []
    sold = 300.0 + sum(rows[n].window_uplift for n in result.selected if rows[n].line.sku_id == "D")
    if sold < 500.0:
        assert [s.shortfall_units for s in result.clearance_shortfalls] == [
            pytest.approx(500.0 - sold)
        ]
    else:
        assert result.clearance_shortfalls == ()


# --- regional budget caps --------------------------------------------------------------------


def test_a_regional_budget_cap_limits_the_promo_cost_spent_in_its_region() -> None:
    rows = [
        Row(line("A"), 100.0, promo_cost=1_000.0),
        Row(line("B"), 80.0, promo_cost=1_000.0),
        Row(line("C", region=Region.SOUTH), 50.0, promo_cost=1_000.0),
    ]

    result = run(rows, regional_budget_caps={"North": 1_500.0})

    assert result.plan.lines == (rows[0].line, rows[2].line)
    assert result.binding_constraints == (
        BindingConstraint(
            kind=ConstraintKind.REGIONAL_BUDGET,
            source=ConstraintSource.BRIEF,
            limit=1_500.0,
            region=Region.NORTH,
            evidence=BindingEvidence.EXACT,
            objective_gain=80.0,
        ),
    )
    assert [(e.option.sku_id, e.reasons) for e in result.not_selected] == [
        ("B", (NotSelectedReason.OVER_REGIONAL_BUDGET,))
    ]
    assert len(run(rows).plan.lines) == 3


# --- the KVI price tolerance -----------------------------------------------------------------

KVI_A = FakeFacts(kvis={("A", Region.NORTH): 75.0})
"""A is a KVI the competitor sells at ₹75 in the North: 20% off (₹80) is 6.7% dearer, 25% off
(₹75) matches."""
A20 = line("A", depth_pct=20)
A25 = line("A", depth_pct=25)


def test_the_kvi_tolerance_keeps_kvi_promo_prices_near_the_competitor_when_enabled() -> None:
    rows = [Row(A20, 100.0), Row(A25, 60.0)]

    assert run(rows, KVI_A).plan.lines == (A20,)
    result = run(rows, KVI_A, kvi_price_tolerance=0.02)
    assert result.plan.lines == (A25,)
    assert result.eligible == 1
    assert result.binding_constraints == (
        BindingConstraint(
            kind=ConstraintKind.KVI_PRICE_TOLERANCE,
            source=ConstraintSource.BRIEF,
            limit=0.02,
            evidence=BindingEvidence.EXACT,
            objective_gain=40.0,
        ),
    )
    assert result.why_chosen[0].best_for_sku_region


def test_company_policy_can_enable_the_kvi_tolerance_itself() -> None:
    enabled = CompanyPolicy(kvi_price_tolerance_enabled=True)

    result = run([Row(A20, 100.0), Row(A25, 60.0)], KVI_A, enabled)

    assert result.plan.lines == (A25,)
    (binding,) = result.binding_constraints
    assert (binding.kind, binding.source) == (
        ConstraintKind.KVI_PRICE_TOLERANCE,
        ConstraintSource.COMPANY_POLICY,
    )


def test_an_option_that_breaks_the_kvi_tolerance_is_listed_with_that_reason() -> None:
    result = run([Row(A20, 100.0), Row(line("B"), 10.0)], KVI_A, kvi_price_tolerance=0.02)

    assert result.plan.lines == (line("B"),)
    assert [(e.option, e.reasons) for e in result.not_selected] == [
        (A20, (NotSelectedReason.BREAKS_KVI_TOLERANCE,))
    ]


# --- tighten-only brief values ---------------------------------------------------------------


def test_the_briefs_tighter_promoted_sku_cap_binds_as_a_brief_constraint() -> None:
    rows = [Row(line("A"), 100.0), Row(line("B"), 80.0)]

    result = run(rows, max_promoted_skus_per_category_per_region=1)

    assert result.plan.lines == (rows[0].line,)
    (binding,) = result.binding_constraints
    assert (binding.kind, binding.source, binding.limit) == (
        ConstraintKind.MAX_PROMOTED_SKUS,
        ConstraintSource.BRIEF,
        1,
    )


def test_a_brief_value_that_would_loosen_policy_is_kept_at_policy_and_reported() -> None:
    rows = [
        Row(line("A"), 900.0, revenue=10_000.0, gross_profit=1_000.0),  # 10%
        Row(line("B"), 100.0, revenue=10_000.0, gross_profit=3_000.0),  # 30%
    ]

    result = run(rows, min_margin=0.05)

    # The 15% margin floor holds: A and B together blend to 20%, A alone to 10%.
    assert result.plan.lines == (rows[0].line, rows[1].line)
    (finding,) = result.policy_findings
    assert (finding.field, finding.requested, finding.applied) == ("min_margin", 0.05, 0.15)
