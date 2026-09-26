"""The CP-SAT optimiser (SPEC §9.4, ADR 0036): hypothesis properties and hand-computed optima.

Instances are built by hand: each promo option's numbers are pinned in a PromoOptions table,
and a fake stands in for the SKU facts and the pairwise cannibalisation of option pairs.
Every returned plan is checked with `validate_plan`, which is independent of the optimiser
(ADR 0012).
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

import numpy as np
import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

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
from promopilot.economics import effective_unit_price
from promopilot.guardrails import LineFacts, PlanFacts, SkuFacts, ViolationCode, validate_plan
from promopilot.models.demand import OPTION_COLUMNS, Prediction, PredictionContext
from promopilot.optimizer import (
    TABLE_COLUMNS,
    OptimisationResult,
    OptionContext,
    PromoOptions,
    PruneReason,
    SolverSettings,
    SolveStatus,
    generate_options,
    solve,
)

WINDOW = PromoWindow(start_week=60, end_week=61)
SEED = 0
PER_LINE = {ViolationCode.STOCK, ViolationCode.MAX_DISCOUNT, ViolationCode.BELOW_COST}
PER_LINE |= {ViolationCode.WINDOW}


def request(budget: float = 100_000.0, min_margin: float | None = None) -> PlanningRequest:
    return PlanningRequest(
        as_of_week=58,
        scope=Scope(regions=(Region.NORTH, Region.SOUTH), categories=("Snacks", "Beverages")),
        promo_window=WINDOW,
        marketing_budget=budget,
        min_margin=min_margin,
    )


def line(sku_id: str, /, **changes: Any) -> PlanLine:
    fields: dict[str, Any] = {
        "sku_id": sku_id,
        "region": Region.NORTH,
        "mechanism": Mechanism.PCT_OFF,
        "depth_pct": 20,
        "duration_weeks": 2,
        "start_week": 60,
        "target_segment": TargetSegment.ALL_CUSTOMERS,
    }
    return PlanLine.model_validate(fields | changes)


@dataclass(frozen=True)
class Row:
    """One promo option and the numbers the optimiser reads (rupees)."""

    line: PlanLine
    value: float
    promo_cost: float = 1_000.0
    revenue: float = 10_000.0
    gross_profit: float = 3_000.0
    p90_units: float = 100.0
    available_stock: float = 1_000.0
    partner_p90_units: float = 0.0
    partner_available_stock: float = 0.0


def options_of(rows: Sequence[Row]) -> PromoOptions:
    table = pd.DataFrame(0.0, index=range(len(rows)), columns=TABLE_COLUMNS)
    for n, row in enumerate(rows):
        for column in (
            "value",
            "promo_cost",
            "revenue",
            "gross_profit",
            "p90_units",
            "available_stock",
            "partner_p90_units",
            "partner_available_stock",
        ):
            table.loc[n, column] = getattr(row, column)
        table.loc[n, "units"] = row.p90_units * 0.8
        table.loc[n, "incremental_profit"] = row.value
    return PromoOptions(
        lines=tuple(row.line for row in rows),
        table=table,
        enumerated=len(rows),
        pruned=dict.fromkeys(PruneReason, 0),
    )


CATALOGUE = {
    "A": ("Snacks", 100.0, 40.0),
    "B": ("Snacks", 100.0, 50.0),
    "C": ("Beverages", 50.0, 20.0),
    "D": ("Snacks", 80.0, 60.0),
}


@dataclass
class FakeFacts:
    """SKU facts from CATALOGUE, and pinned pairwise terms (0 for any other pair)."""

    overstocked: set[tuple[str, Region]] = field(default_factory=set)
    pairwise: dict[frozenset[PlanLine], float] = field(default_factory=dict)
    asked: list[tuple[PlanLine, PlanLine]] = field(default_factory=list)

    def sku(self, sku_id: str, region: Region) -> SkuFacts:
        category, base_price, unit_cost = CATALOGUE[sku_id]
        return SkuFacts(
            category=category,
            base_price=base_price,
            unit_cost=unit_cost,
            overstocked=(sku_id, region) in self.overstocked,
        )

    def pairwise_cannibalisation(
        self, pairs: Sequence[tuple[PlanLine, PlanLine]]
    ) -> Sequence[float]:
        self.asked += pairs
        return [self.pairwise.get(frozenset(pair), 0.0) for pair in pairs]


def run(
    rows: Sequence[Row],
    facts: FakeFacts | None = None,
    policy: CompanyPolicy | None = None,
    **changes: Any,
) -> OptimisationResult:
    return solve(
        request(**changes),
        options_of(rows),
        facts or FakeFacts(),
        policy or CompanyPolicy(),
        seed=SEED,
    )


def chosen(result: OptimisationResult) -> list[PlanLine]:
    return list(result.plan.lines)


def plan_facts(rows: Sequence[Row], picked: Iterable[int], facts: FakeFacts) -> PlanFacts:
    lines = []
    for n in picked:
        row = rows[n]
        partner = row.line.bundle_partner_sku_id
        lines.append(
            LineFacts(
                line=row.line,
                anchor=facts.sku(row.line.sku_id, row.line.region),
                partner=None if partner is None else facts.sku(partner, row.line.region),
                expected_units=row.p90_units * 0.8,
                p90_units=row.p90_units,
                available_stock=row.available_stock,
                expected_revenue=row.revenue,
                expected_gross_profit=row.gross_profit,
                promo_cost=row.promo_cost,
            )
        )
    return PlanFacts(lines=tuple(lines))


def objective_of(rows: Sequence[Row], picked: Sequence[int], facts: FakeFacts) -> int:
    """The objective in paise: values less the pairwise terms of every selected pair."""
    total = sum(round(rows[n].value * 100) for n in picked)
    for a, b in combinations(picked, 2):
        total -= round(facts.pairwise.get(frozenset((rows[a].line, rows[b].line)), 0.0) * 100)
    return total


# --- random small instances ------------------------------------------------------------

SKUS = sorted(CATALOGUE)
money = st.integers(min_value=0, max_value=500_000).map(lambda paise: paise / 100)


@st.composite
def lines_(draw: st.DrawFn) -> PlanLine:
    sku_id = draw(st.sampled_from(SKUS))
    bundle = draw(st.booleans())
    duration = draw(st.integers(1, 2))
    return line(
        sku_id,
        region=draw(st.sampled_from([Region.NORTH, Region.SOUTH])),
        mechanism=Mechanism.BUNDLE if bundle else Mechanism.PCT_OFF,
        bundle_partner_sku_id=(
            draw(st.sampled_from([s for s in SKUS if s != sku_id])) if bundle else None
        ),
        depth_pct=draw(st.sampled_from([10, 20, 25] if bundle else [5, 10, 20, 30, 50, 60])),
        duration_weeks=duration,
        start_week=draw(st.integers(59 if duration == 1 else 60, 62 - duration)),
        target_segment=draw(st.sampled_from(list(TargetSegment))),
    )


@st.composite
def rows_(draw: st.DrawFn) -> Row:
    revenue = draw(st.integers(100_00, 20_000_00)) / 100
    stock = draw(st.sampled_from([50.0, 1_000.0]))
    return Row(
        line=draw(lines_()),
        value=draw(st.integers(-3_000_00, 5_000_00)) / 100,
        promo_cost=draw(money),
        revenue=revenue,
        gross_profit=round(revenue * draw(st.integers(-20, 50)) / 100, 2),
        p90_units=draw(st.sampled_from([40.0, 100.0])),
        available_stock=stock,
        partner_p90_units=draw(st.sampled_from([0.0, 40.0, 100.0])),
        partner_available_stock=draw(st.sampled_from([50.0, 1_000.0])),
    )


@dataclass(frozen=True)
class Instance:
    rows: list[Row]
    facts: FakeFacts
    budget: float
    min_margin: float | None
    policy: CompanyPolicy

    def solve(
        self, budget: float | None = None, min_margin: float | None = None
    ) -> OptimisationResult:
        return solve(
            request(
                budget or self.budget, min_margin if min_margin is not None else self.min_margin
            ),
            options_of(self.rows),
            self.facts,
            self.policy,
            seed=SEED,
        )


def together(a: PlanLine, b: PlanLine) -> bool:
    """Whether two lines could both run and overlap: same region, no SKU in common, a week
    and a segment in common. Only such pairs have a pairwise term (ADR 0033)."""
    weeks = set(range(a.start_week, a.start_week + a.duration_weeks))
    everyone = TargetSegment.ALL_CUSTOMERS
    return (
        a.region is b.region
        and not set(a.skus) & set(b.skus)
        and bool(weeks & set(range(b.start_week, b.start_week + b.duration_weeks)))
        and (
            everyone in (a.target_segment, b.target_segment) or a.target_segment is b.target_segment
        )
    )


@st.composite
def instances(draw: st.DrawFn) -> Instance:
    rows = draw(st.lists(rows_(), min_size=1, max_size=8))
    overstocked = draw(
        st.sets(st.tuples(st.sampled_from(SKUS), st.sampled_from([Region.NORTH, Region.SOUTH])))
    )
    pairwise = {
        frozenset((a.line, b.line)): draw(st.integers(-1_000_00, 3_000_00)) / 100
        for a, b in combinations(rows, 2)
        if together(a.line, b.line) and draw(st.booleans())
    }
    return Instance(
        rows=rows,
        facts=FakeFacts(overstocked=set(overstocked), pairwise=pairwise),
        budget=draw(st.integers(1, 1_500_000)) / 100,
        min_margin=draw(st.one_of(st.none(), st.integers(0, 40).map(lambda p: p / 100))),
        policy=CompanyPolicy(
            margin_floor=draw(st.integers(0, 30)) / 100,
            max_promoted_skus_per_category_per_region=draw(st.integers(1, 3)),
        ),
    )


def best_by_brute_force(instance: Instance) -> tuple[int, int | None]:
    """The best objective (paise) over every plan of positive-value options that break no
    per-line rule: first among the plans `validate_plan` accepts, then among those that also
    keep 10 paise clear of the budget and of the margin line (None if there are none)."""
    rows, facts = instance.rows, instance.facts
    planning = request(instance.budget, instance.min_margin)
    lone = [
        n
        for n, row in enumerate(rows)
        if round(row.value * 100) >= 1
        and not (
            row.line.bundle_partner_sku_id is not None
            and row.partner_p90_units > row.partner_available_stock
        )
        and not any(
            violation.code in PER_LINE
            for violation in validate_plan(plan_facts(rows, [n], facts), planning, instance.policy)
        )
    ]
    minimum = max(instance.min_margin or 0.0, instance.policy.margin_floor)
    loose = 0
    tight: int | None = None
    for size in range(len(lone) + 1):
        for picked in combinations(lone, size):
            if validate_plan(plan_facts(rows, picked, facts), planning, instance.policy):
                continue
            score = objective_of(rows, picked, facts)
            loose = max(loose, score)
            clear = sum(rows[n].promo_cost for n in picked) <= instance.budget - 0.10
            short = sum(minimum * rows[n].revenue - rows[n].gross_profit for n in picked)
            if clear and (not picked or short <= -0.10):
                tight = score if tight is None else max(tight, score)
    return loose, tight


PROPERTY = settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])


@PROPERTY
@given(instances())
def test_every_returned_plan_satisfies_every_hard_constraint(instance: Instance) -> None:
    result = instance.solve()

    assert result.status is SolveStatus.OPTIMAL
    picked = list(result.selected)
    assert [instance.rows[n].line for n in picked] == list(result.plan.lines)
    plan = plan_facts(instance.rows, picked, instance.facts)
    assert validate_plan(plan, request(instance.budget, instance.min_margin), instance.policy) == ()
    assert all(round(instance.rows[n].value * 100) >= 1 for n in picked)
    assert round(result.objective * 100) == objective_of(instance.rows, picked, instance.facts)


@PROPERTY
@given(instances())
def test_the_plan_is_optimal_up_to_rounding_at_the_constraint_lines(instance: Instance) -> None:
    result = instance.solve()

    loose, tight = best_by_brute_force(instance)
    objective = round(result.objective * 100)
    assert objective <= loose
    assert tight is None or objective >= tight


@PROPERTY
@given(instances(), st.integers(1, 99))
def test_tightening_the_budget_never_increases_the_objective(instance: Instance, cut: int) -> None:
    tighter = max(0.01, round(instance.budget * cut / 100, 2))

    assert instance.solve(budget=tighter).objective <= instance.solve().objective


@PROPERTY
@given(instances(), st.integers(1, 30))
def test_raising_the_minimum_margin_never_increases_the_objective(
    instance: Instance, raise_by: int
) -> None:
    before = instance.min_margin or 0.0
    higher = min(0.99, before + raise_by / 100)

    assert (
        instance.solve(min_margin=higher).objective <= instance.solve(min_margin=before).objective
    )


# --- the depth of a single (SKU, region) -----------------------------------------------


@st.composite
def depth_ladders(draw: st.DrawFn) -> list[Row]:
    """One SKU in one region whose options differ only in depth: deeper costs strictly more
    and earns a strictly lower margin; values are distinct (ADR 0036)."""
    depths = sorted(draw(st.sets(st.sampled_from([5, 10, 15, 20, 25, 30, 40, 50]), min_size=1)))
    costs = sorted(
        draw(st.sets(st.integers(1_00, 5_000_00), min_size=len(depths), max_size=len(depths)))
    )
    margins = sorted(
        draw(st.sets(st.integers(-10, 45), min_size=len(depths), max_size=len(depths))),
        reverse=True,
    )
    values = draw(
        st.lists(st.integers(1, 10_000_00), min_size=len(depths), max_size=len(depths), unique=True)
    )
    return [
        Row(
            line=line("D", depth_pct=depth),
            value=value / 100,
            promo_cost=cost / 100,
            revenue=10_000.0,
            gross_profit=100.0 * margin,
        )
        for depth, cost, margin, value in zip(depths, costs, margins, values, strict=True)
    ]


def average_depth(result: OptimisationResult) -> float:
    depths = [line.depth_pct for line in result.plan.lines]
    return float(np.mean(depths)) if depths else 0.0


OVERSTOCKED_D = FakeFacts(overstocked={("D", Region.NORTH)})
"""D sells below unit cost at every depth, so it must be overstocked to be promoted."""
NO_FLOOR = CompanyPolicy(margin_floor=0.0)


@PROPERTY
@given(depth_ladders(), st.integers(1, 5_000_00), st.integers(1, 99))
def test_lowering_the_budget_never_deepens_the_average_discount(
    rows: list[Row], budget: int, cut: int
) -> None:
    budget_rupees = budget / 100
    lower = max(0.01, round(budget_rupees * cut / 100, 2))

    before = run(rows, OVERSTOCKED_D, NO_FLOOR, budget=budget_rupees)
    after = run(rows, OVERSTOCKED_D, NO_FLOOR, budget=lower)

    assert average_depth(after) <= average_depth(before)


@PROPERTY
@given(depth_ladders(), st.integers(-10, 45), st.integers(1, 30))
def test_raising_the_minimum_margin_never_deepens_the_average_discount(
    rows: list[Row], margin: int, raise_by: int
) -> None:
    before_margin = max(0, margin) / 100
    after_margin = min(0.99, before_margin + raise_by / 100)

    before = run(rows, OVERSTOCKED_D, NO_FLOOR, min_margin=before_margin)
    after = run(rows, OVERSTOCKED_D, NO_FLOOR, min_margin=after_margin)

    assert average_depth(after) <= average_depth(before)


def test_a_deeper_option_can_win_on_a_lower_budget_across_skus() -> None:
    """Why the depth property is stated per (SKU, region) (ADR 0036): with two SKUs, a lower
    budget can drop a shallow line and keep a deep one."""
    rows = [
        Row(line("A", depth_pct=10), value=100.0, promo_cost=10.0),
        Row(line("B", depth_pct=40), value=1_000.0, promo_cost=50.0),
    ]

    assert average_depth(run(rows, budget=60.0)) == 25
    assert average_depth(run(rows, budget=50.0)) == 40


# --- hand-computed optima --------------------------------------------------------------


def test_only_lines_with_a_positive_value_are_selected() -> None:
    rows = [
        Row(line("A"), value=500.0),
        Row(line("B"), value=-10.0),
        Row(line("C"), value=0.004),  # rounds to 0 paise
        Row(line("A", region=Region.SOUTH), value=0.01),
    ]

    result = run(rows)

    assert chosen(result) == [rows[0].line, rows[3].line]
    assert result.objective == pytest.approx(500.01)
    assert result.eligible == 2


def test_the_budget_picks_the_best_affordable_set() -> None:
    rows = [
        Row(line("A"), value=600.0, promo_cost=700.0),
        Row(line("B"), value=500.0, promo_cost=500.0),
        Row(line("C"), value=400.0, promo_cost=500.0),
    ]

    assert chosen(run(rows, budget=1_000.0)) == [rows[1].line, rows[2].line]
    assert chosen(run(rows, budget=1_200.0)) == [rows[0].line, rows[1].line]


def test_the_blended_margin_meets_the_minimum_margin_never_below_the_policy_floor() -> None:
    rows = [
        Row(line("A"), value=900.0, revenue=10_000.0, gross_profit=1_000.0),  # 10%
        Row(line("B"), value=100.0, revenue=10_000.0, gross_profit=3_000.0),  # 30%
    ]
    floor_ten = CompanyPolicy(margin_floor=0.10)

    assert chosen(run(rows, policy=floor_ten)) == [rows[0].line, rows[1].line]
    assert chosen(run(rows, policy=floor_ten, min_margin=0.25)) == [rows[1].line]
    # A minimum margin below the floor is held at the floor.
    assert chosen(run(rows, policy=CompanyPolicy(margin_floor=0.25), min_margin=0.05)) == [
        rows[1].line
    ]


def test_a_bundle_partner_is_locked_in_its_region() -> None:
    bundle = line("A", mechanism=Mechanism.BUNDLE, bundle_partner_sku_id="C")
    rows = [
        Row(bundle, value=1_000.0),
        Row(line("C"), value=900.0),
        Row(line("C", region=Region.SOUTH), value=900.0),
    ]

    result = run(rows)

    assert chosen(result) == [bundle, rows[2].line]
    rows[0] = Row(bundle, value=800.0)
    assert chosen(run(rows)) == [rows[1].line, rows[2].line]


def test_a_bundle_partner_counts_toward_its_own_categorys_limit() -> None:
    bundle = line("A", mechanism=Mechanism.BUNDLE, bundle_partner_sku_id="C")
    rows = [Row(bundle, value=1_000.0), Row(line("D"), value=100.0)]
    one_per_category = CompanyPolicy(max_promoted_skus_per_category_per_region=1)

    # A (Snacks) and C (Beverages) fill both categories; D (Snacks) has no room.
    assert chosen(run(rows, policy=one_per_category)) == [bundle]
    two = CompanyPolicy(max_promoted_skus_per_category_per_region=2)
    assert chosen(run(rows, policy=two)) == [bundle, rows[1].line]


def test_an_overstocked_sku_not_named_for_clearance_is_selected_only_for_its_value() -> None:
    facts = FakeFacts(overstocked={("D", Region.NORTH), ("D", Region.SOUTH)})
    # D sells below cost at 30% (₹56 < ₹60): only an overstocked D may.
    cleared = Row(line("D", depth_pct=30), value=300.0)
    not_worth_it = Row(line("D", region=Region.SOUTH, depth_pct=30), value=-50.0)

    result = run([cleared, not_worth_it], facts)

    assert chosen(result) == [cleared.line]
    assert chosen(run([cleared], FakeFacts())) == []  # not overstocked: below cost


def test_options_that_break_a_per_line_rule_are_never_selected() -> None:
    rows = [
        Row(line("A"), value=900.0, p90_units=1_001.0, available_stock=1_000.0),
        Row(
            line("B", mechanism=Mechanism.BUNDLE, bundle_partner_sku_id="C"),
            value=900.0,
            partner_p90_units=60.0,
            partner_available_stock=50.0,
        ),
        Row(line("A", region=Region.SOUTH, depth_pct=60), value=900.0),  # over 50% maximum
        Row(line("B", region=Region.SOUTH, depth_pct=60), value=900.0),  # below cost too
        Row(line("C", start_week=61), value=900.0),  # ends after the window
        Row(line("C", region=Region.SOUTH), value=10.0),
    ]

    assert chosen(run(rows)) == [rows[5].line]


def test_two_substitutes_are_not_promoted_together_when_cannibalisation_outweighs() -> None:
    a, b = Row(line("A"), value=1_000.0), Row(line("B"), value=800.0)

    heavy = FakeFacts(pairwise={frozenset((a.line, b.line)): 900.0})
    light = FakeFacts(pairwise={frozenset((a.line, b.line)): 300.0})

    assert chosen(run([a, b], heavy)) == [a.line]
    assert run([a, b], heavy).objective == pytest.approx(1_000.0)
    assert chosen(run([a, b], light)) == [a.line, b.line]
    assert run([a, b], light).objective == pytest.approx(1_500.0)
    assert run([a, b], light).pairwise_cannibalisation == pytest.approx(300.0)


def test_a_negative_pairwise_term_is_credited() -> None:
    a, b = Row(line("A"), value=1_000.0), Row(line("B"), value=800.0)
    facts = FakeFacts(pairwise={frozenset((a.line, b.line)): -200.0})

    result = run([a, b], facts, budget=2_000.0)

    assert result.objective == pytest.approx(2_000.0)


def test_pairs_are_priced_only_where_both_could_run_together() -> None:
    rows = [
        Row(line("A"), value=10.0),
        Row(line("B"), value=10.0),
        Row(line("B", region=Region.SOUTH), value=10.0),  # another region
        Row(line("C", start_week=60, duration_weeks=1), value=10.0),
        Row(line("D", start_week=61, duration_weeks=1), value=10.0),  # no week shared with C
        Row(line("A", depth_pct=10), value=10.0),  # the same SKU as row 0
        Row(
            line("C", target_segment=TargetSegment.FAMILIES, start_week=61, duration_weeks=1), 10.0
        ),
        Row(line("D", target_segment=TargetSegment.PREMIUM, start_week=61, duration_weeks=1), 10.0),
        Row(line("C", depth_pct=10), value=-5.0),  # ineligible
    ]
    facts = FakeFacts()

    run(rows, facts)

    asked = {frozenset(pair) for pair in facts.asked}
    assert frozenset((rows[0].line, rows[1].line)) in asked
    assert frozenset((rows[3].line, rows[0].line)) in asked
    assert frozenset((rows[1].line, rows[2].line)) not in asked
    assert frozenset((rows[3].line, rows[4].line)) not in asked
    assert frozenset((rows[0].line, rows[5].line)) not in asked
    assert frozenset((rows[6].line, rows[7].line)) not in asked
    assert not any(rows[8].line in pair for pair in asked)


def test_the_same_input_gives_the_same_plan() -> None:
    rows = [
        Row(line(sku_id, depth_pct=depth), value=100.0) for sku_id in SKUS for depth in (10, 20)
    ]
    rows += [Row(line(sku_id, region=Region.SOUTH), value=100.0) for sku_id in SKUS]

    first = run(rows, budget=3_500.0)
    again = run(rows, budget=3_500.0)
    in_parallel = solve(
        request(budget=3_500.0),
        options_of(rows),
        FakeFacts(),
        CompanyPolicy(),
        settings=SolverSettings(workers=2),
        seed=SEED,
    )

    assert first == again
    assert in_parallel.plan == first.plan
    assert first.objective == pytest.approx(300.0)


def test_an_empty_candidate_set_gives_an_empty_optimal_plan() -> None:
    result = run([])

    assert result.status is SolveStatus.OPTIMAL
    assert result.plan.lines == ()
    assert result.objective == 0
    assert (result.eligible, result.pairs) == (0, 0)


def test_solver_settings_are_validated() -> None:
    with pytest.raises(ValueError, match="time limit"):
        SolverSettings(time_limit_seconds=0)
    with pytest.raises(ValueError, match="worker"):
        SolverSettings(workers=0)


# --- per-region differences through option generation ----------------------------------

HOLIDAY = {Region.NORTH: 61, Region.SOUTH: 60}
PRODUCTS = pd.DataFrame(
    {"sku_id": ["A"], "category": ["Snacks"], "base_price": [100.0], "unit_cost": [40.0]}
)


class HolidayDemand:
    """100 baseline units a week; a week lifts units by depth x 1, or x 5 in the region's
    holiday week. Fixed cost ₹1,000 a week."""

    def predict(self, options: Sequence[PlanLine], context: PredictionContext) -> Prediction:
        rows = []
        for option in options:
            price = effective_unit_price(option.mechanism, 100.0, option.depth_pct)
            weeks = range(option.start_week, option.start_week + option.duration_weeks)
            lift = [5.0 if week == HOLIDAY[option.region] else 1.0 for week in weeks]
            units = sum(100.0 * (1 + k * option.depth_pct / 100) for k in lift)
            baseline = 100.0 * option.duration_weeks
            gross = units * (price - 40.0)
            rows.append(
                dict.fromkeys(OPTION_COLUMNS, 0.0)
                | {
                    "units": units,
                    "baseline_units": baseline,
                    "incremental_units": units - baseline,
                    "revenue": units * price,
                    "gross_profit": gross,
                    "margin": (price - 40.0) / price,
                    "promo_cost": units * (100.0 - price) + 1_000.0 * option.duration_weeks,
                    "incremental_profit": gross - baseline * 60.0 - 1_000.0 * option.duration_weeks,
                }
            )
        return Prediction(
            options=pd.DataFrame(rows, columns=OPTION_COLUMNS), segments=pd.DataFrame()
        )

    def line_paths(self, options: Sequence[PlanLine], context: PredictionContext) -> pd.DataFrame:
        raise NotImplementedError("generation never asks for line paths")

    def baseline(
        self,
        weeks: Iterable[int],
        *,
        regions: Sequence[str] | None = None,
        store_ids: Sequence[str] | None = None,
        sku_ids: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        return pd.DataFrame(columns=["week_id", "store_id", "sku_id", "segment", "units"])


class NoRelations:
    def substitutes(self, sku_id: str) -> pd.DataFrame:
        return pd.DataFrame(columns=["sku_id", "theta", "std_error", "q_value"])

    def complements(self, sku_id: str) -> pd.DataFrame:
        return pd.DataFrame(columns=["sku_id", "theta", "lift", "support", "std_error"])


class Regional(FakeFacts):
    def sku(self, sku_id: str, region: Region) -> SkuFacts:
        return SkuFacts(category="Snacks", base_price=100.0, unit_cost=40.0, overstocked=False)


def test_per_region_plans_follow_regional_holidays() -> None:
    stock = pd.DataFrame(
        {
            "sku_id": ["A", "A"],
            "region": ["North", "South"],
            "available_stock": [1e6, 1e6],
            "is_overstock": [False, False],
        }
    )
    planning = PlanningRequest(
        as_of_week=58,
        scope=Scope(regions=(Region.NORTH, Region.SOUTH), categories=("Snacks",)),
        promo_window=WINDOW,
        marketing_budget=1e6,
    )
    options = generate_options(
        planning,
        OptionContext(
            demand_model=HolidayDemand(),
            relations=NoRelations(),
            products=PRODUCTS,
            stock=stock,
        ),
        mechanisms=[Mechanism.PCT_OFF],
        target_segments=[TargetSegment.ALL_CUSTOMERS],
    )

    result = solve(planning, options, Regional(), CompanyPolicy(margin_floor=0.0), seed=SEED)

    by_region = {line.region: line for line in result.plan.lines}
    assert set(by_region) == {Region.NORTH, Region.SOUTH}
    for region, holiday in HOLIDAY.items():
        assert (by_region[region].start_week, by_region[region].duration_weeks) == (holiday, 1)
