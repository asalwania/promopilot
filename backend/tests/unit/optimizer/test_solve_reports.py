"""What `solve` reports beside the plan (ADR 0038): binding constraints, why each plan line was
chosen, and the best options left out with their reasons.

Instances are the hand-built ones of `test_solve`. A constraint binds when dropping it gives a
strictly better objective, so the properties drop each one through the public inputs and
re-solve.
"""

from dataclasses import dataclass, replace
from typing import Any

import pytest
from hypothesis import given

from promopilot.domain import (
    BindingConstraint,
    BindingEvidence,
    CompanyPolicy,
    ConstraintKind,
    ConstraintSource,
    NotSelectedReason,
    PlanLine,
    Region,
    SelectionReason,
    SelectionReasonCode,
    SolveStatus,
)
from promopilot.guardrails import SkuFacts
from promopilot.optimizer import OptimisationResult, PromoOptions, SolverSettings, solve
from tests.unit.optimizer.test_solve import (
    PROPERTY,
    SEED,
    FakeFacts,
    Instance,
    Row,
    instances,
    line,
    options_of,
    request,
    run,
)

# --- binding constraints -------------------------------------------------------------------


def objective(result: OptimisationResult) -> int:
    return round(result.objective * 100)


def kinds(result: OptimisationResult) -> set[ConstraintKind]:
    """The constraints reported binding; small instances always settle each one."""
    assert all(c.evidence is BindingEvidence.EXACT for c in result.binding_constraints)
    return {constraint.kind for constraint in result.binding_constraints}


def without_margin(instance: Instance) -> Instance:
    """The margin constraint dropped: every option at a 100% margin cannot break it."""
    return replace(instance, rows=[replace(row, gross_profit=row.revenue) for row in instance.rows])


def without_budget(instance: Instance) -> Instance:
    return replace(instance, budget=10_000_000_000.0)


def without_caps(instance: Instance) -> Instance:
    return replace(
        instance,
        policy=instance.policy.model_copy(update={"max_promoted_skus_per_category_per_region": 99}),
    )


@dataclass
class OneCategoryFacts(FakeFacts):
    def sku(self, sku_id: str, region: Region) -> SkuFacts:
        return super().sku(sku_id, region).model_copy(update={"category": "Snacks"})


def one_group(instance: Instance) -> Instance:
    """Every option in the North and one category: a single promoted-SKU cap."""

    def north(plan_line: PlanLine) -> PlanLine:
        return plan_line.model_copy(update={"region": Region.NORTH})

    facts = instance.facts
    return replace(
        instance,
        rows=[replace(row, line=north(row.line)) for row in instance.rows],
        facts=OneCategoryFacts(
            overstocked={(sku_id, Region.NORTH) for sku_id, _ in facts.overstocked},
            pairwise={
                frozenset(north(member) for member in pair): term
                for pair, term in facts.pairwise.items()
            },
        ),
    )


def gains(result: OptimisationResult, relaxed: OptimisationResult) -> bool:
    assert relaxed.status is SolveStatus.OPTIMAL
    assert objective(relaxed) >= objective(result), "dropping a constraint never hurts"
    return objective(relaxed) > objective(result)


@PROPERTY
@given(instances())
def test_the_budget_and_margin_are_reported_binding_exactly_when_dropping_them_gains(
    instance: Instance,
) -> None:
    result = instance.solve()
    assert result.status is SolveStatus.OPTIMAL

    budget = gains(result, without_budget(instance).solve())
    margin = gains(result, without_margin(instance).solve())

    assert (ConstraintKind.MARKETING_BUDGET in kinds(result)) == budget
    margins = {ConstraintKind.MINIMUM_MARGIN, ConstraintKind.MARGIN_FLOOR}
    assert bool(kinds(result) & margins) == margin
    if kinds(result) & {ConstraintKind.MAX_PROMOTED_SKUS}:
        assert gains(result, without_caps(instance).solve())


@PROPERTY
@given(instances().map(one_group))
def test_the_promoted_sku_cap_is_reported_binding_exactly_when_dropping_it_gains(
    instance: Instance,
) -> None:
    result = instance.solve()

    capped = [c for c in result.binding_constraints if c.kind is ConstraintKind.MAX_PROMOTED_SKUS]
    assert all(c.evidence is BindingEvidence.EXACT for c in capped)

    assert bool(capped) == gains(result, without_caps(instance).solve())
    for constraint in capped:
        assert (constraint.category, constraint.region) == ("Snacks", Region.NORTH)


@PROPERTY
@given(instances())
def test_a_binding_constraint_reports_what_dropping_it_gains(instance: Instance) -> None:
    result = instance.solve()
    dropped = {
        ConstraintKind.MARKETING_BUDGET: without_budget,
        ConstraintKind.MINIMUM_MARGIN: without_margin,
        ConstraintKind.MARGIN_FLOOR: without_margin,
    }

    for constraint in result.binding_constraints:
        assert constraint.objective_gain is not None
        assert constraint.objective_gain >= 0.01
        if constraint.kind in dropped:
            relaxed = dropped[constraint.kind](instance).solve()
            assert constraint.objective_gain == pytest.approx(relaxed.objective - result.objective)


A = line("A")
B = line("B")


def test_a_budget_that_leaves_money_unspent_still_binds() -> None:
    result = run(
        [Row(A, 100.0, promo_cost=1_000.0), Row(B, 80.0, promo_cost=1_000.0)], budget=1_500
    )

    assert result.binding_constraints == (
        BindingConstraint(
            kind=ConstraintKind.MARKETING_BUDGET,
            source=ConstraintSource.BRIEF,
            limit=1_500.0,
            evidence=BindingEvidence.EXACT,
            objective_gain=80.0,
        ),
    )


def test_the_briefs_minimum_margin_binds_above_the_floor() -> None:
    rows = [Row(A, 100.0, gross_profit=3_000.0), Row(B, 80.0, gross_profit=1_000.0)]

    result = run(rows, min_margin=0.25)

    assert result.binding_constraints == (
        BindingConstraint(
            kind=ConstraintKind.MINIMUM_MARGIN,
            source=ConstraintSource.BRIEF,
            limit=0.25,
            evidence=BindingEvidence.EXACT,
            objective_gain=80.0,
        ),
    )


def test_the_company_policy_margin_floor_binds_when_the_brief_sets_none_higher() -> None:
    rows = [Row(A, 100.0, gross_profit=3_000.0), Row(B, 80.0, gross_profit=1_000.0)]

    result = run(rows, policy=CompanyPolicy(margin_floor=0.25), min_margin=0.20)

    assert [(c.kind, c.source, c.limit) for c in result.binding_constraints] == [
        (ConstraintKind.MARGIN_FLOOR, ConstraintSource.COMPANY_POLICY, 0.25)
    ]


def test_the_promoted_sku_cap_binds_per_category_and_region() -> None:
    rows = [Row(A, 100.0), Row(B, 80.0), Row(line("A", region=Region.SOUTH), 50.0)]

    result = run(rows, policy=CompanyPolicy(max_promoted_skus_per_category_per_region=1))

    assert result.binding_constraints == (
        BindingConstraint(
            kind=ConstraintKind.MAX_PROMOTED_SKUS,
            source=ConstraintSource.COMPANY_POLICY,
            limit=1,
            category="Snacks",
            region=Region.NORTH,
            evidence=BindingEvidence.EXACT,
            objective_gain=80.0,
        ),
    )


def test_constraints_left_unsettled_when_the_time_for_re_solving_runs_out_are_unproven() -> None:
    result = solve(
        request(budget=1_500),
        options_of([Row(A, 100.0, promo_cost=1_000.0), Row(B, 80.0, promo_cost=1_000.0)]),
        FakeFacts(),
        CompanyPolicy(),
        settings=SolverSettings(binding_time_limit_seconds=0),
        seed=SEED,
    )

    assert result.status is SolveStatus.OPTIMAL
    # Every option keeps a 30% margin, so the 15% floor is settled without re-solving.
    assert [(c.kind, c.evidence, c.objective_gain) for c in result.binding_constraints] == [
        (ConstraintKind.MARKETING_BUDGET, BindingEvidence.UNPROVEN, None),
    ]


def no_time(rows: list[Row], policy: CompanyPolicy | None = None, **changes: Any) -> Any:
    return solve(
        request(**changes),
        options_of(rows),
        FakeFacts(),
        policy or CompanyPolicy(),
        settings=SolverSettings(binding_time_limit_seconds=0),
        seed=SEED,
    )


def test_a_budget_no_plan_could_exhaust_is_settled_as_not_binding_without_re_solving() -> None:
    rows = [
        Row(A, 100.0, promo_cost=1_000.0),
        Row(line("A", depth_pct=30), 90.0, promo_cost=1_400.0),
    ]
    rows.append(Row(B, 80.0, promo_cost=1_000.0))

    # At most one line per SKU: the costliest plan spends 1,400 + 1,000 = 2,400.
    assert no_time(rows, budget=2_400).binding_constraints == ()
    assert [c.kind for c in no_time(rows, budget=2_399).binding_constraints] == [
        ConstraintKind.MARKETING_BUDGET
    ]


def test_a_margin_no_plan_could_break_is_settled_as_not_binding_without_re_solving() -> None:
    rows = [Row(A, 100.0, gross_profit=2_500.0), Row(B, 80.0, gross_profit=2_600.0)]

    assert no_time(rows, min_margin=0.25).binding_constraints == ()
    assert [c.kind for c in no_time(rows, min_margin=0.26).binding_constraints] == [
        ConstraintKind.MINIMUM_MARGIN
    ]


def test_a_cap_with_room_for_every_sku_is_settled_as_not_binding_even_with_more_options() -> None:
    rows = [Row(A, 100.0), Row(line("A", depth_pct=30), 90.0), Row(line("A", depth_pct=10), 50.0)]
    one = CompanyPolicy(max_promoted_skus_per_category_per_region=1)

    assert no_time(rows, policy=one).binding_constraints == ()


def test_re_solving_prices_each_pair_of_options_once() -> None:
    rows = [Row(line(sku_id), 100.0, promo_cost=1_000.0) for sku_id in "ABCD"]
    facts = FakeFacts(pairwise={frozenset((rows[0].line, rows[1].line)): 30.0})

    result = run(rows, facts, budget=2_500)

    assert result.binding_constraints
    asked = [frozenset(pair) for pair in facts.asked]
    assert len(asked) == len(set(asked))


def test_nothing_binds_when_every_worthwhile_option_is_selected() -> None:
    result = run([Row(A, 100.0), Row(B, -80.0)])

    assert result.binding_constraints == ()


# --- why chosen -----------------------------------------------------------------------------


def with_parts(options: PromoOptions, n: int, **parts: float) -> PromoOptions:
    """Split row n's value into incremental profit, cannibalisation, halo and clearance."""
    table = options.table.copy()
    for column, amount in parts.items():
        table.loc[n, column] = amount
    row = {name: float(amount) for name, amount in table.iloc[n].items()}
    table.loc[n, "value"] = (
        row["incremental_profit"]
        - row["cannibalised_profit"]
        + row["halo_profit"]
        + row["clearance_value"]
    )
    return replace(options, table=table)


def solve_options(options: PromoOptions, facts: FakeFacts | None = None, **changes: Any) -> Any:
    return solve(request(**changes), options, facts or FakeFacts(), CompanyPolicy(), seed=SEED)


def test_a_profitable_line_is_chosen_for_its_incremental_profit() -> None:
    result = run([Row(A, 100.0)])

    (why,) = result.why_chosen
    assert why.reasons == (
        SelectionReason(code=SelectionReasonCode.INCREMENTAL_PROFIT, amount=100),
    )
    assert why.value == 100.0
    assert why.best_for_sku_region


def test_a_clearance_line_is_chosen_for_its_clearance_value_and_halo() -> None:
    options = with_parts(
        options_of([Row(A, 0.0)]),
        0,
        incremental_profit=-50.0,
        cannibalised_profit=20.0,
        halo_profit=10.0,
        clearance_value=200.0,
    )

    result = solve_options(options)

    (why,) = result.why_chosen
    assert why.reasons == (
        SelectionReason(code=SelectionReasonCode.CLEARANCE_VALUE, amount=200.0),
        SelectionReason(code=SelectionReasonCode.HALO, amount=10.0),
    )
    assert why.value == 140.0


def test_a_line_that_is_not_its_skus_best_option_says_so() -> None:
    deep = Row(line("A", depth_pct=30), 100.0, promo_cost=2_000.0)
    shallow = Row(A, 50.0, promo_cost=500.0)

    result = run([deep, shallow], budget=1_000)

    assert result.plan.lines == (A,)
    assert not result.why_chosen[0].best_for_sku_region


# --- not selected ---------------------------------------------------------------------------


def reasons(result: OptimisationResult) -> dict[str, tuple[NotSelectedReason, ...]]:
    return {entry.option.sku_id: entry.reasons for entry in result.not_selected}


def test_an_option_not_worth_a_paisa_alone_is_low_uplift() -> None:
    result = run([Row(A, 100.0), Row(B, -5.0)])

    assert reasons(result) == {"B": (NotSelectedReason.LOW_UPLIFT,)}
    assert result.not_selected[0].value == -5.0


def test_an_option_the_budget_cannot_fit_is_over_budget() -> None:
    result = run(
        [Row(A, 100.0, promo_cost=1_000.0), Row(B, 80.0, promo_cost=1_000.0)], budget=1_500
    )

    assert reasons(result) == {"B": (NotSelectedReason.OVER_BUDGET,)}


def test_an_option_that_would_pull_the_blended_margin_under_the_minimum_breaks_margin() -> None:
    rows = [Row(A, 100.0, gross_profit=3_000.0), Row(B, 80.0, gross_profit=1_000.0)]

    result = run(rows, min_margin=0.25)

    assert reasons(result) == {"B": (NotSelectedReason.BREAKS_MARGIN,)}


def test_an_option_in_a_full_category_and_region_hits_the_promoted_sku_cap() -> None:
    result = run(
        [Row(A, 100.0), Row(B, 80.0)],
        policy=CompanyPolicy(max_promoted_skus_per_category_per_region=1),
    )

    assert reasons(result) == {"B": (NotSelectedReason.MAX_PROMOTED_SKUS,)}


def test_an_option_that_loses_more_with_a_plan_line_than_it_is_worth_cannibalises_it() -> None:
    facts = FakeFacts(pairwise={frozenset((A, B)): 150.0})

    result = run([Row(A, 100.0), Row(B, 80.0)], facts)

    assert reasons(result) == {"B": (NotSelectedReason.CANNIBALISES,)}
    assert result.not_selected[0].cannibalises == ("A",)


def test_an_option_whose_p90_exceeds_stock_is_out_of_stock() -> None:
    result = run([Row(A, 100.0), Row(B, 80.0, p90_units=2_000.0, available_stock=1_000.0)])

    assert reasons(result) == {"B": (NotSelectedReason.OUT_OF_STOCK,)}


def test_an_option_outside_company_policy_breaks_policy() -> None:
    too_deep = line("B", depth_pct=60)

    result = run([Row(A, 100.0), Row(too_deep, 80.0)])

    assert reasons(result) == {"B": (NotSelectedReason.BREAKS_POLICY,)}


def test_every_rule_an_option_breaks_is_listed() -> None:
    rows = [
        Row(A, 100.0, promo_cost=1_000.0, gross_profit=3_000.0),
        Row(B, 80.0, promo_cost=1_000.0, gross_profit=1_000.0),
    ]

    result = run(rows, budget=1_500, min_margin=0.25)

    assert reasons(result) == {
        "B": (NotSelectedReason.OVER_BUDGET, NotSelectedReason.BREAKS_MARGIN)
    }


def test_each_sku_and_region_left_out_is_listed_once_with_its_best_option() -> None:
    rows = [
        Row(A, 100.0),
        Row(line("B", depth_pct=10), -30.0),
        Row(line("B", depth_pct=30), -10.0),
        Row(line("B", region=Region.SOUTH), -20.0),
    ]

    result = run(rows)

    assert [(e.option.sku_id, e.option.region, e.value) for e in result.not_selected] == [
        ("B", Region.NORTH, -10.0),
        ("B", Region.SOUTH, -20.0),
    ]


def test_at_most_five_are_listed_best_value_first() -> None:
    skus = ["A", "B", "C", "D"]
    rows = [
        Row(line(sku_id, region=region), -float(n + 1))
        for n, (sku_id, region) in enumerate(
            (sku_id, region) for region in (Region.NORTH, Region.SOUTH) for sku_id in skus
        )
    ]

    result = run(rows)

    assert [entry.value for entry in result.not_selected] == [-1.0, -2.0, -3.0, -4.0, -5.0]


def test_a_bundle_partner_in_the_plan_is_not_listed() -> None:
    bundle = line("A", mechanism="BUNDLE", bundle_partner_sku_id="B", depth_pct=20)

    result = run([Row(bundle, 100.0), Row(B, -10.0), Row(line("B", depth_pct=10), 50.0)])

    assert result.plan.lines == (bundle,)
    assert result.not_selected == ()


# --- properties -----------------------------------------------------------------------------


@PROPERTY
@given(instances())
def test_every_plan_line_says_why_and_every_listed_option_says_why_not(instance: Instance) -> None:
    result = instance.solve()

    assert len(result.why_chosen) == len(result.plan.lines)
    for why in result.why_chosen:
        assert why.reasons
        assert all(reason.amount > 0 for reason in why.reasons)
    occupied = {(sku_id, line.region) for line in result.plan.lines for sku_id in line.skus}
    listed = [(entry.option.sku_id, entry.option.region) for entry in result.not_selected]
    assert len(listed) <= 5
    assert len(set(listed)) == len(listed)
    values = [entry.value for entry in result.not_selected]
    assert values == sorted(values, reverse=True)
    for entry in result.not_selected:
        assert not {(sku_id, entry.option.region) for sku_id in entry.option.skus} & occupied
        assert entry.reasons
        assert NotSelectedReason.TIME_LIMIT not in entry.reasons
        assert bool(entry.cannibalises) == (NotSelectedReason.CANNIBALISES in entry.reasons)
