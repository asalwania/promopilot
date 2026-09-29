"""Infeasible requests and their minimal relaxation (SPEC §9.4, AG-06, ADR 0007, ADR 0044).

A request is infeasible when no plan reaches every clearance target within its other
constraints. `solve` then reports `INFEASIBLE` with the closest plan (ADR 0040), and the
smallest change to the brief's constraints that would make it feasible: the least sum of each
change as a share of the brief's value. Company policy is never relaxed; when only lowering a
target can help, policy binds.
"""

from dataclasses import replace
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from promopilot.domain import (
    BindingConstraint,
    BindingEvidence,
    ClearanceShortfall,
    CompanyPolicy,
    ConstraintKind,
    ConstraintSource,
    Region,
    Relaxation,
    RelaxedConstraint,
    SolveStatus,
)
from promopilot.optimizer import (
    ClearanceBaseline,
    OptimisationResult,
    SolverSettings,
    relaxed_request,
    solve,
)
from tests.unit.optimizer.test_solve import (
    CATALOGUE,
    PROPERTY,
    SEED,
    STARVED,
    FakeFacts,
    Instance,
    Row,
    best_by_brute_force,
    instances,
    line,
    options_of,
    request,
    run,
)

D_NORTH = ClearanceBaseline(
    sku_id="D", region=Region.NORTH, available_stock=1_000.0, baseline_units=300.0
)
"""D sells 300 of its 1,000 units over the window unpromoted: a 50% target needs 200 more."""
D10 = line("D", depth_pct=10)
D30 = line("D", depth_pct=30)


def target(sell_through: float = 0.5, *sku_ids: str) -> list[dict[str, Any]]:
    return [{"sku_id": sku_id, "sell_through": sell_through} for sku_id in sku_ids or ("D",)]


def empty(sku_id: str) -> ClearanceBaseline:
    """A SKU that sells nothing unpromoted: any target needs a plan line."""
    return ClearanceBaseline(
        sku_id=sku_id, region=Region.NORTH, available_stock=1_000.0, baseline_units=0.0
    )


def changes(result: OptimisationResult) -> list[tuple[ConstraintKind, Any]]:
    assert result.relaxation is not None
    return [(c.kind, c.relaxed) for c in result.relaxation.changes]


# --- examples ----------------------------------------------------------------------------------


def test_a_reachable_request_is_not_relaxed() -> None:
    result = run(
        [Row(D30, 50.0, window_uplift=250.0)], clearance=[D_NORTH], clearance_targets=target()
    )

    assert result.status is SolveStatus.OPTIMAL
    assert result.relaxation is None


def test_when_only_policy_binds_the_target_comes_down_and_policy_is_said_to_bind() -> None:
    result = run(
        [Row(D10, 100.0, window_uplift=100.0)], clearance=[D_NORTH], clearance_targets=target()
    )

    assert result.status is SolveStatus.INFEASIBLE
    # The closest plan still comes back, with its shortfall (ADR 0040).
    assert result.plan.lines == (D10,)
    assert [s.shortfall_units for s in result.clearance_shortfalls] == [pytest.approx(100.0)]
    assert result.relaxation is not None
    assert result.relaxation.policy_binds
    assert result.relaxation.proven
    (change,) = result.relaxation.changes
    assert change.model_dump() == {
        "kind": ConstraintKind.CLEARANCE_TARGET,
        "source": ConstraintSource.BRIEF,
        "region": None,
        "sku_id": "D",
        "current": 0.5,
        "relaxed": pytest.approx(0.4),
        "change": pytest.approx(0.2),
        "policy_allows": pytest.approx(0.4),
    }


def test_a_budget_rise_is_proposed_when_it_is_the_smallest_change() -> None:
    rows = [
        Row(D30, 50.0, promo_cost=2_000.0, window_uplift=250.0),
        Row(D10, 100.0, promo_cost=500.0, window_uplift=100.0),
    ]

    result = run(rows, clearance=[D_NORTH], clearance_targets=target(), budget=1_800.0)

    # ₹1,800 -> ₹2,000 is 11% more budget; 50% -> 40% sell-through would be a 20% cut.
    assert result.status is SolveStatus.INFEASIBLE
    assert result.relaxation is not None
    assert not result.relaxation.policy_binds
    assert changes(result) == [(ConstraintKind.MARKETING_BUDGET, 2_000.0)]
    assert result.relaxation.changes[0].change == pytest.approx(200 / 1_800)
    assert result.binding_constraints == (
        BindingConstraint(
            kind=ConstraintKind.MARKETING_BUDGET,
            source=ConstraintSource.BRIEF,
            limit=1_800.0,
            evidence=BindingEvidence.INFEASIBLE,
            objective_gain=None,
        ),
        BindingConstraint(
            kind=ConstraintKind.CLEARANCE_TARGET,
            source=ConstraintSource.BRIEF,
            limit=0.5,
            sku_id="D",
            region=Region.NORTH,
            evidence=BindingEvidence.INFEASIBLE,
            objective_gain=None,
        ),
    )


def test_the_target_comes_down_when_that_is_smaller_than_the_budget_rise() -> None:
    rows = [
        Row(D30, 50.0, promo_cost=2_000.0, window_uplift=250.0),
        Row(D10, 100.0, promo_cost=500.0, window_uplift=100.0),
    ]

    result = run(rows, clearance=[D_NORTH], clearance_targets=target(), budget=1_000.0)

    # Doubling the budget is a 100% change; 50% -> 40% is a 20% one.
    assert changes(result) == [(ConstraintKind.CLEARANCE_TARGET, pytest.approx(0.4))]
    assert result.relaxation is not None
    assert not result.relaxation.policy_binds
    assert result.relaxation.changes[0].policy_allows is None


def test_a_regional_budget_cap_is_relaxed_like_the_budget() -> None:
    rows = [
        Row(D30, 50.0, promo_cost=2_000.0, window_uplift=250.0),
        Row(D10, 100.0, promo_cost=500.0, window_uplift=100.0),
    ]

    result = run(
        rows,
        clearance=[D_NORTH],
        clearance_targets=target(),
        regional_budget_caps={"North": 1_800.0},
    )

    assert result.relaxation is not None
    (change,) = result.relaxation.changes
    assert (change.kind, change.region, change.relaxed) == (
        ConstraintKind.REGIONAL_BUDGET,
        Region.NORTH,
        2_000.0,
    )


def test_the_briefs_minimum_margin_comes_down_but_never_below_the_policy_floor() -> None:
    rows = [
        Row(D30, 50.0, window_uplift=250.0, gross_profit=2_500.0),  # 25%
        Row(D10, 100.0, window_uplift=100.0, gross_profit=3_500.0),  # 35%
    ]

    result = run(rows, clearance=[D_NORTH], clearance_targets=target(), min_margin=0.30)

    # 30% -> 25% is a 17% change; 50% -> 40% sell-through a 20% one.
    assert changes(result) == [(ConstraintKind.MINIMUM_MARGIN, pytest.approx(0.25))]

    below_floor = [replace(rows[0], gross_profit=1_000.0), rows[1]]  # 10% < the 15% floor
    held = run(below_floor, clearance=[D_NORTH], clearance_targets=target(), min_margin=0.30)
    assert held.relaxation is not None
    assert held.relaxation.policy_binds
    assert changes(held) == [(ConstraintKind.CLEARANCE_TARGET, pytest.approx(0.4))]


def test_the_policy_margin_floor_is_never_relaxed() -> None:
    rows = [
        Row(D30, 50.0, window_uplift=250.0, gross_profit=1_000.0),  # 10% < the 15% floor
        Row(D10, 100.0, window_uplift=100.0),
    ]

    result = run(rows, clearance=[D_NORTH], clearance_targets=target())

    assert result.relaxation is not None
    assert result.relaxation.policy_binds
    assert changes(result) == [(ConstraintKind.CLEARANCE_TARGET, pytest.approx(0.4))]


def test_the_briefs_tighter_promoted_sku_cap_is_raised_up_to_policys() -> None:
    rows = [Row(line(sku_id, depth_pct=10), 100.0, window_uplift=150.0) for sku_id in "ABD"]
    baselines = [empty(sku_id) for sku_id in "ABD"]

    result = run(
        rows,
        clearance=baselines,
        clearance_targets=target(0.1, "A", "B", "D"),
        max_promoted_skus_per_category_per_region=2,
    )

    # A third promoted Snacks SKU is a 50% change; dropping a target is a 100% one.
    assert result.status is SolveStatus.INFEASIBLE
    assert changes(result) == [(ConstraintKind.MAX_PROMOTED_SKUS, 3.0)]
    policy_cap = CompanyPolicy(max_promoted_skus_per_category_per_region=2)
    held = run(
        rows, None, policy_cap, clearance=baselines, clearance_targets=target(0.1, "A", "B", "D")
    )
    assert held.relaxation is not None
    assert held.relaxation.policy_binds
    (dropped,) = held.relaxation.changes
    assert (dropped.kind, dropped.relaxed, dropped.change) == (
        ConstraintKind.CLEARANCE_TARGET,
        None,
        1.0,
    )


def test_a_kvi_tolerance_the_brief_turned_on_is_turned_off() -> None:
    kvis = FakeFacts(kvis={("A", Region.NORTH): 75.0, ("B", Region.NORTH): 75.0})
    rows = [Row(line(sku_id, depth_pct=20), 100.0, window_uplift=150.0) for sku_id in "AB"]

    result = run(
        rows,
        kvis,
        clearance=[empty("A"), empty("B")],
        clearance_targets=target(0.1, "A", "B"),
        kvi_price_tolerance=0.02,
    )

    # Turning the tolerance off is one 100% change; dropping both targets would be two.
    assert changes(result) == [(ConstraintKind.KVI_PRICE_TOLERANCE, None)]
    held = run(
        rows,
        kvis,
        CompanyPolicy(kvi_price_tolerance_enabled=True),
        clearance=[empty("A"), empty("B")],
        clearance_targets=target(0.1, "A", "B"),
    )
    assert held.relaxation is not None
    assert held.relaxation.policy_binds
    assert {c.kind for c in held.relaxation.changes} == {ConstraintKind.CLEARANCE_TARGET}


def timed_out(
    rows: list[Row], targets: list[dict[str, Any]], *, check: float = 10.0
) -> OptimisationResult:
    """Solve with a closest-plan search and a main solve starved of work, so the closest
    phase ends unproven at the empty plan; `check` is the relaxation budget, half of which
    the feasibility check with every target hard may take (ADR 0074)."""
    return solve(
        request(clearance_targets=targets),
        options_of(rows, [empty(sku_id) for sku_id in "AD"]),
        FakeFacts(),
        CompanyPolicy(),
        settings=SolverSettings(
            deterministic_limit=STARVED,
            binding_deterministic_limit=0,
            relaxation_deterministic_limit=check,
        ),
        seed=SEED,
    )


LADDER = [
    Row(line(sku_id, depth_pct=depth), float(depth), promo_cost=900.0, window_uplift=depth * 5.0)
    for sku_id in "ABCD"
    for depth in (10, 20, 30, 40)
]
"""A and D each sell at most 200 of their 1,000 units: a 50% target is out of reach, 10% is not."""


def test_a_missed_target_the_closest_search_left_unsettled_is_proven_infeasible() -> None:
    result = timed_out(LADDER, target(0.5, "A", "D"))

    # The closest search timed out, but the check with every target hard proves no plan
    # reaches them (ADR 0074): infeasible, with the relaxation.
    assert result.status is SolveStatus.INFEASIBLE
    assert missed(result) == {("A", Region.NORTH), ("D", Region.NORTH)}
    assert result.relaxation is not None
    assert result.relaxation.proven
    assert result.relaxation.changes
    assert result.binding_constraints
    assert all(c.evidence is BindingEvidence.INFEASIBLE for c in result.binding_constraints)


def test_targets_the_closest_search_left_short_are_met_when_a_plan_reaches_them() -> None:
    result = timed_out(LADDER, target(0.1, "A", "D"))

    # The check finds a plan that reaches every target: the targets stay the brief's.
    assert result.status is not SolveStatus.INFEASIBLE
    assert result.clearance_shortfalls == ()
    assert result.relaxation is None
    assert {line.sku_id for line in result.plan.lines} >= {"A", "D"}


def test_a_missed_target_neither_proven_nor_reached_in_time_is_infeasible_unproven() -> None:
    result = timed_out(LADDER, target(0.5, "A", "D"), check=STARVED)

    # A plan that misses a target is never FEASIBLE (ADR 0074): approval waits for the
    # manager to accept the relaxation, which says it is not proven.
    assert result.status is SolveStatus.INFEASIBLE
    assert result.clearance_shortfalls
    assert result.relaxation is not None
    assert not result.relaxation.proven
    assert all(c.evidence is BindingEvidence.INFEASIBLE for c in result.binding_constraints)


def test_a_work_budget_that_runs_out_ends_in_the_same_place_whatever_the_wall_clock_net() -> None:
    rows = [
        Row(line(sku_id, depth_pct=depth), float(depth), window_uplift=depth * 10.0)
        for sku_id in "ABD"
        for depth in (10, 20)
    ]

    def solved(wall: float) -> OptimisationResult:
        return solve(
            request(clearance_targets=target()),
            options_of(rows, [D_NORTH]),
            FakeFacts(),
            CompanyPolicy(),
            settings=SolverSettings(
                deterministic_limit=1e-6,
                binding_deterministic_limit=1e-6,
                relaxation_deterministic_limit=1e-6,
                time_limit_seconds=wall,
                binding_time_limit_seconds=wall,
                relaxation_time_limit_seconds=wall,
            ),
            seed=SEED,
        )

    assert solved(5.0) == solved(500.0)


def test_relaxation_settings_are_validated() -> None:
    with pytest.raises(ValueError, match="relaxation"):
        SolverSettings(relaxation_time_limit_seconds=0)


def test_applying_a_relaxation_rewrites_only_the_brief_values_it_changes() -> None:
    rows = [
        Row(D30, 50.0, promo_cost=2_000.0, window_uplift=250.0),
        Row(D10, 100.0, promo_cost=500.0, window_uplift=100.0),
    ]
    asked = request(1_800.0, clearance_targets=target())
    result = solve(asked, options_of(rows, [D_NORTH]), FakeFacts(), CompanyPolicy(), seed=SEED)
    assert result.relaxation is not None

    relaxed = relaxed_request(asked, result.relaxation)

    assert relaxed == asked.model_copy(update={"marketing_budget": 2_000.0})
    again = solve(relaxed, options_of(rows, [D_NORTH]), FakeFacts(), CompanyPolicy(), seed=SEED)
    assert again.status is SolveStatus.OPTIMAL
    assert again.clearance_shortfalls == ()


# --- properties ------------------------------------------------------------------------------


def freed(instance: Instance) -> Instance:
    """Every brief constraint but the clearance targets relaxed as far as policy allows."""
    return replace(
        instance,
        budget=sum(row.promo_cost for row in instance.rows) + 1.0,
        min_margin=None,
        caps={},
        kvi_tolerance=None,
        brief_cap=None,
    )


def missed(result: OptimisationResult) -> set[tuple[str, Region]]:
    return {(s.sku_id, s.region) for s in result.clearance_shortfalls}


@st.composite
def squeezed(draw: st.DrawFn) -> Instance:
    """Clearance targets that options can reach, under a brief whose budget, regional cap,
    minimum margin, promoted-SKU cap and KVI tolerance are squeezed: often the brief's own
    constraints, not company policy, make these infeasible."""
    named = draw(st.lists(st.sampled_from(["A", "B", "D"]), min_size=1, max_size=3, unique=True))
    rows = [
        Row(
            line(sku_id, depth_pct=draw(st.sampled_from([10, 20, 30, 40]))),
            value=draw(st.integers(-2_000_00, 3_000_00)) / 100,
            promo_cost=draw(st.integers(100_00, 5_000_00)) / 100,
            revenue=10_000.0,
            gross_profit=100.0 * draw(st.integers(5, 45)),
            window_uplift=draw(st.sampled_from([60.0, 150.0, 250.0, 400.0])),
        )
        for sku_id in named
        for _ in range(draw(st.integers(1, 3)))
    ]
    spend = sum(row.promo_cost for row in rows)
    kvis = {
        (sku_id, Region.NORTH): CATALOGUE[sku_id][1] * 0.6
        for sku_id in named
        if draw(st.booleans())
    }
    return Instance(
        rows=rows,
        facts=FakeFacts(kvis=kvis),
        budget=max(1.0, round(spend * draw(st.integers(5, 80)) / 100, 2)),
        min_margin=draw(st.one_of(st.none(), st.integers(16, 45).map(lambda p: p / 100))),
        policy=CompanyPolicy(max_promoted_skus_per_category_per_region=3),
        targets=tuple((sku_id, draw(st.sampled_from([0.2, 0.3, 0.4]))) for sku_id in named),
        clearance=tuple(
            ClearanceBaseline(
                sku_id=sku_id,
                region=Region.NORTH,
                available_stock=1_000.0,
                baseline_units=float(draw(st.integers(0, 150))),
            )
            for sku_id in named
        ),
        caps={Region.NORTH: round(spend * draw(st.integers(5, 80)) / 100, 2)}
        if draw(st.booleans())
        else {},
        kvi_tolerance=draw(st.sampled_from([None, 0.02])),
        brief_cap=draw(st.sampled_from([None, 1, 2])),
    )


cases = st.one_of(instances(), squeezed())


@PROPERTY
@given(cases)
def test_infeasible_instances_are_reported_infeasible_with_a_relaxation(
    instance: Instance,
) -> None:
    result = instance.solve()

    infeasible = best_by_brute_force(instance).least_shortfall > 0
    assert (result.status is SolveStatus.INFEASIBLE) == infeasible
    assert (result.relaxation is not None) == infeasible
    if not infeasible:
        return
    assert result.relaxation is not None
    assert result.relaxation.proven
    assert result.relaxation.changes
    assert result.relaxation.policy_binds == (
        best_by_brute_force(freed(instance)).least_shortfall > 0
    )
    assert all(c.evidence is BindingEvidence.INFEASIBLE for c in result.binding_constraints)
    assert {
        (c.sku_id, c.region)
        for c in result.binding_constraints
        if c.kind is ConstraintKind.CLEARANCE_TARGET
    } == missed(result)


@PROPERTY
@given(cases)
def test_applying_the_relaxation_makes_the_instance_feasible(instance: Instance) -> None:
    result = instance.solve()
    if result.relaxation is None:
        return

    planning = instance.planning()
    relaxed = relaxed_request(planning, result.relaxation)
    again = solve(
        relaxed,
        options_of(instance.rows, instance.clearance),
        instance.facts,
        instance.policy,
        seed=SEED,
    )

    assert again.status is SolveStatus.OPTIMAL
    assert again.clearance_shortfalls == ()
    assert again.relaxation is None


@PROPERTY
@given(cases)
def test_relaxations_never_touch_company_policy(instance: Instance) -> None:
    result = instance.solve()
    if result.relaxation is None:
        return

    policy = instance.policy
    floor = policy.margin_floor
    for change in result.relaxation.changes:
        assert change.source is ConstraintSource.BRIEF
        assert change.change > 0
        if change.kind is ConstraintKind.MINIMUM_MARGIN:
            assert instance.min_margin is not None
            assert instance.min_margin > floor
            assert change.relaxed is not None
            assert floor - 1e-9 <= change.relaxed < change.current
        elif change.kind is ConstraintKind.MAX_PROMOTED_SKUS:
            assert instance.brief_cap is not None
            assert change.relaxed is not None
            assert change.relaxed <= policy.max_promoted_skus_per_category_per_region
        elif change.kind is ConstraintKind.KVI_PRICE_TOLERANCE:
            assert instance.kvi_tolerance is not None
        elif change.kind is ConstraintKind.MARKETING_BUDGET:
            assert change.relaxed is not None
            assert change.relaxed > instance.budget
        elif change.kind is ConstraintKind.REGIONAL_BUDGET:
            assert change.region in instance.caps
        else:
            assert change.kind is ConstraintKind.CLEARANCE_TARGET
            assert change.sku_id in dict(instance.targets)
            assert change.relaxed is None or change.relaxed < change.current


@PROPERTY
@given(cases)
def test_no_change_of_a_proven_relaxation_can_be_left_out(instance: Instance) -> None:
    result = instance.solve()
    if result.relaxation is None or len(result.relaxation.changes) < 2:
        return
    assert result.relaxation.proven

    planning = instance.planning()
    for left_out in result.relaxation.changes:
        others = result.relaxation.model_copy(
            update={"changes": tuple(c for c in result.relaxation.changes if c != left_out)}
        )
        partly = relaxed_request(planning, others)
        again = solve(
            partly,
            options_of(instance.rows, instance.clearance),
            instance.facts,
            instance.policy,
            seed=SEED,
        )
        assert again.status is SolveStatus.INFEASIBLE, left_out


def test_an_infeasible_plan_still_reports_every_shortfall() -> None:
    result = run(
        [Row(D10, 100.0, window_uplift=100.0)], clearance=[D_NORTH], clearance_targets=target()
    )

    assert result.clearance_shortfalls == (
        ClearanceShortfall(
            sku_id="D",
            region=Region.NORTH,
            target=0.5,
            expected_sell_through=0.4,
            shortfall_units=100.0,
        ),
    )


def test_a_relaxation_of_company_policy_cannot_be_applied() -> None:
    policy_change = Relaxation(
        changes=(
            RelaxedConstraint(
                kind=ConstraintKind.MARGIN_FLOOR, current=0.15, relaxed=0.1, change=1 / 3
            ),
        ),
        policy_binds=False,
        proven=True,
    )

    with pytest.raises(ValueError, match="company policy"):
        relaxed_request(request(), policy_change)
