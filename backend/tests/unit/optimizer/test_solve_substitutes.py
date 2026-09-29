"""Strong substitutes are never promoted together (ADR 0075).

Two SKUs the relations model detects as substitutes, with an estimated θ at least the company
policy's `strong_substitute_min_theta`, are never in plan lines that run together: in one
region, with a promo week and a target segment in common, a BUNDLE's partner included. The
optimiser keeps them apart as a hard constraint, reports it binding when dropping it gains,
and names it as the reason a left-out option was not selected.
"""

from typing import Any

import pytest

from promopilot.domain import (
    BindingEvidence,
    CompanyPolicy,
    ConstraintKind,
    ConstraintSource,
    Mechanism,
    NotSelectedReason,
    Region,
    TargetSegment,
)
from promopilot.guardrails import ViolationCode, validate_plan
from promopilot.optimizer import ClearanceBaseline, OptimisationResult
from tests.unit.optimizer.test_solve import (
    FakeFacts,
    Row,
    chosen,
    line,
    plan_facts,
    request,
    run,
)

STRONG = FakeFacts(thetas={frozenset(("A", "B")): 0.6})
"""A and B are strong substitutes: θ 0.6 is above the default 0.35."""


def skus(result: OptimisationResult) -> list[str]:
    return sorted(plan_line.sku_id for plan_line in result.plan.lines)


def guard(result: OptimisationResult) -> list[Any]:
    return [
        binding
        for binding in result.binding_constraints
        if binding.kind is ConstraintKind.STRONG_SUBSTITUTES
    ]


def assert_valid(rows: list[Row], result: OptimisationResult, facts: FakeFacts) -> None:
    facts_of_plan = plan_facts(rows, result.selected, facts)
    assert validate_plan(facts_of_plan, request(), CompanyPolicy()) == ()


def test_two_strong_substitutes_are_never_promoted_together() -> None:
    rows = [Row(line("A"), value=500.0), Row(line("B"), value=400.0)]

    result = run(rows, STRONG)

    assert skus(result) == ["A"]
    assert_valid(rows, result, STRONG)
    # Without the relations model's estimate they run together.
    assert skus(run(rows)) == ["A", "B"]


def test_one_of_the_pair_shifts_to_other_weeks() -> None:
    rows = [
        Row(line("A", duration_weeks=1, start_week=60), value=500.0),
        Row(line("B", duration_weeks=1, start_week=60), value=400.0),
        Row(line("B", duration_weeks=1, start_week=61), value=300.0),
    ]

    result = run(rows, STRONG)

    assert [(pl.sku_id, pl.start_week) for pl in chosen(result)] == [("A", 60), ("B", 61)]


def test_one_of_the_pair_shifts_to_another_segment() -> None:
    rows = [
        Row(line("A", target_segment=TargetSegment.FAMILIES), value=500.0),
        Row(line("B"), value=400.0),
        Row(line("B", target_segment=TargetSegment.PREMIUM), value=100.0),
    ]

    result = run(rows, STRONG)

    assert [(pl.sku_id, pl.target_segment) for pl in chosen(result)] == [
        ("A", TargetSegment.FAMILIES),
        ("B", TargetSegment.PREMIUM),
    ]


def test_strong_substitutes_in_different_regions_run_at_once() -> None:
    rows = [Row(line("A"), value=500.0), Row(line("B", region=Region.SOUTH), value=400.0)]

    assert skus(run(rows, STRONG)) == ["A", "B"]


def test_a_substitute_below_the_policy_threshold_is_not_kept_apart() -> None:
    rows = [Row(line("A"), value=500.0), Row(line("B"), value=400.0)]
    weak = FakeFacts(thetas={frozenset(("A", "B")): 0.34})

    assert skus(run(rows, weak)) == ["A", "B"]
    assert skus(run(rows, STRONG, CompanyPolicy(strong_substitute_min_theta=0.7))) == ["A", "B"]
    assert skus(run(rows, weak, CompanyPolicy(strong_substitute_min_theta=0.3))) == ["A"]


def test_a_bundle_partner_counts_as_promoted() -> None:
    bundle = line("C", mechanism=Mechanism.BUNDLE, depth_pct=20, bundle_partner_sku_id="A")
    rows = [Row(bundle, value=500.0), Row(line("B"), value=400.0)]

    assert skus(run(rows, STRONG)) == ["C"]


def test_a_bundle_of_two_strong_substitutes_is_never_selected() -> None:
    bundle = line("A", mechanism=Mechanism.BUNDLE, depth_pct=20, bundle_partner_sku_id="B")
    rows = [Row(bundle, value=900.0), Row(line("C"), value=100.0)]

    result = run(rows, STRONG)

    assert skus(result) == ["C"]
    left_out = [option for option in result.not_selected if option.option == bundle]
    assert left_out
    assert NotSelectedReason.STRONG_SUBSTITUTE in left_out[0].reasons


def test_the_rule_binds_with_what_dropping_it_gains() -> None:
    rows = [Row(line("A"), value=500.0), Row(line("B"), value=400.0)]

    [binding] = guard(run(rows, STRONG))

    assert binding.source is ConstraintSource.COMPANY_POLICY
    assert binding.limit == pytest.approx(0.35)
    assert binding.evidence in (BindingEvidence.EXACT, BindingEvidence.LOWER_BOUND)
    assert binding.objective_gain == pytest.approx(400.0)


def test_the_rule_does_not_bind_when_the_pair_is_not_worth_running_together() -> None:
    rows = [Row(line("A"), value=500.0), Row(line("B"), value=400.0)]
    facts = FakeFacts(
        thetas={frozenset(("A", "B")): 0.6},
        pairwise={frozenset((rows[0].line, rows[1].line)): 450.0},
    )

    assert guard(run(rows, facts)) == []


def test_no_other_constraint_is_proven_binding_by_breaking_the_rule() -> None:
    """The budget allows one line, and the rule allows only one: a swap that breaks the rule
    proves nothing about the budget."""
    rows = [
        Row(line("A"), value=500.0, promo_cost=100.0),
        Row(line("B"), value=400.0, promo_cost=100.0),
    ]

    result = run(rows, STRONG, budget=150.0)

    assert ConstraintKind.MARKETING_BUDGET not in {b.kind for b in result.binding_constraints}


def test_a_left_out_strong_substitute_names_the_plan_sku_it_would_run_with() -> None:
    rows = [Row(line("A"), value=500.0), Row(line("B"), value=400.0)]

    result = run(rows, STRONG)

    [option] = [option for option in result.not_selected if option.option.sku_id == "B"]
    assert option.reasons == (NotSelectedReason.STRONG_SUBSTITUTE,)
    assert option.cannibalises == ("A",)


def test_the_closest_plan_to_a_clearance_target_keeps_the_rule_too() -> None:
    rows = [
        Row(line("A"), value=500.0, window_uplift=300.0),
        Row(line("B"), value=400.0, window_uplift=300.0),
    ]
    clearance = [
        ClearanceBaseline(
            sku_id=sku_id, region=Region.NORTH, available_stock=500.0, baseline_units=0.0
        )
        for sku_id in ("A", "B")
    ]

    result = run(
        rows,
        STRONG,
        clearance=clearance,
        clearance_targets=[
            {"sku_id": "A", "sell_through": 0.5},
            {"sku_id": "B", "sell_through": 0.5},
        ],
    )

    assert len(result.plan.lines) == 1
    assert result.relaxation is not None
    facts_of_plan = plan_facts(rows, result.selected, STRONG, clearance)
    codes = {v.code for v in validate_plan(facts_of_plan, request(), CompanyPolicy())}
    assert ViolationCode.STRONG_SUBSTITUTES not in codes
