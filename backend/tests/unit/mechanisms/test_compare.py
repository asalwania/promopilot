"""The mechanism comparator (SPEC F-02, ADR 0041), on small hand-built contexts.

Options are generated from the hand-built world of the option-generation tests: A (₹100,
cost ₹40) has one complement, C (₹50, cost ₹30, Beverages); B (₹100, cost ₹85) sells below
cost at BOGO; D (₹60, cost ₹20) has no complement. A fake demand model gives each mechanism
a pinned demand effect beyond price, so one mechanism can be made to dominate.
"""

import math
from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd
import pytest

from promopilot.domain import (
    CompanyPolicy,
    Mechanism,
    MechanismOutcome,
    PlanLine,
    PruneReason,
    Region,
    TargetSegment,
)
from promopilot.economics import effective_unit_price
from promopilot.mechanisms import ComparisonContext, compare
from promopilot.models.demand import OPTION_COLUMNS, Prediction, PredictionContext
from promopilot.optimizer import OptionContext, PromoOptions, generate_options
from tests.unit.optimizer.test_generate_options import (
    COSTS,
    PRICES,
    PRODUCTS,
    FakeDemand,
    FakeRelations,
    request,
    stock,
)

NO_EFFECT = {mechanism: 0.0 for mechanism in Mechanism}


class MechanismDemand(FakeDemand):
    """100 baseline units a week (25 for one segment), lifted by a constant elasticity of -2
    and by each mechanism's pinned demand effect: log units rise by `effects[mechanism]`."""

    def __init__(self, effects: Mapping[Mechanism, float] = NO_EFFECT) -> None:
        super().__init__()
        self.effects = effects

    def predict(self, options: Sequence[PlanLine], context: PredictionContext) -> Prediction:
        rows = []
        for line in options:
            weekly = 100.0 if line.target_segment is TargetSegment.ALL_CUSTOMERS else 25.0
            base, cost = PRICES[line.sku_id], COSTS[line.sku_id]
            price = effective_unit_price(line.mechanism, base, line.depth_pct)
            baseline = weekly * line.duration_weeks
            units = baseline * (price / base) ** -2 * math.exp(self.effects[line.mechanism])
            fixed = CompanyPolicy().fixed_cost_per_line_week[line.mechanism] * line.duration_weeks
            partner = line.bundle_partner_sku_id is not None
            rows.append(
                {
                    "units": units,
                    "units_std": units / 10,
                    "baseline_units": baseline,
                    "pull_forward_units": 0.0,
                    "incremental_units": units - baseline,
                    "revenue": units * price,
                    "gross_profit": units * (price - cost),
                    "margin": (price - cost) / price,
                    "promo_cost": units * (base - price) + fixed,
                    "incremental_profit": units * (price - cost) - baseline * (base - cost) - fixed,
                    "anchor_discount_funding": units * (base - price),
                    "partner_units": 50.0 * line.duration_weeks if partner else 0.0,
                    "partner_units_std": 5.0 * line.duration_weeks if partner else 0.0,
                    "partner_baseline_units": 40.0 * line.duration_weeks if partner else 0.0,
                    "partner_discount_funding": 0.0,
                }
            )
        return Prediction(
            options=pd.DataFrame(rows, columns=OPTION_COLUMNS), segments=pd.DataFrame()
        )


def generated(
    effects: Mapping[Mechanism, float] = NO_EFFECT, inventory: pd.DataFrame | None = None
) -> ComparisonContext:
    options = generate_options(
        request(),
        OptionContext(
            demand_model=MechanismDemand(effects),
            relations=FakeRelations(),
            products=PRODUCTS,
            stock=stock() if inventory is None else inventory,
        ),
    )
    return ComparisonContext(options=options, relations=FakeRelations(), products=PRODUCTS)


def by_mechanism(outcomes: Sequence[MechanismOutcome]) -> dict[Mechanism, MechanismOutcome]:
    return {outcome.mechanism: outcome for outcome in outcomes}


def rows_for(options: PromoOptions, sku_id: str, region: Region, mechanism: Mechanism) -> list[int]:
    return [
        n
        for n, line in enumerate(options.lines)
        if (line.sku_id, line.region, line.mechanism) == (sku_id, region, mechanism)
    ]


# --- which mechanisms are compared ------------------------------------------------------


def test_bundle_is_compared_only_for_a_sku_with_a_complement() -> None:
    context = generated()

    with_complement = by_mechanism(compare("A", Region.NORTH, context))
    without = by_mechanism(compare("D", Region.NORTH, context))

    assert set(with_complement) == set(Mechanism)
    assert set(without) == {Mechanism.PCT_OFF, Mechanism.BOGO, Mechanism.FIXED_PRICE}


def test_a_bundle_suggestion_lists_the_pair_its_lift_and_its_incremental_profit() -> None:
    context = generated()

    bundle = by_mechanism(compare("A", Region.NORTH, context))[Mechanism.BUNDLE].best

    assert bundle is not None
    assert (bundle.anchor_sku_id, bundle.partner_sku_id) == ("A", "C")
    assert bundle.option.bundle_partner_sku_id == "C"
    assert bundle.basket_lift == 2.0
    row = context.options.lines.index(bundle.option)
    assert bundle.incremental_profit == context.options.table["incremental_profit"].iloc[row]


def test_a_bundle_whose_partner_is_no_longer_a_complement_is_not_compared() -> None:
    context = generated()

    class NoComplements(FakeRelations):
        def complements(self, sku_id: str) -> pd.DataFrame:
            return super().complements(sku_id).iloc[0:0]

    detached = ComparisonContext(
        options=context.options, relations=NoComplements(), products=PRODUCTS
    )

    assert Mechanism.BUNDLE not in by_mechanism(compare("A", Region.NORTH, detached))


def test_a_sku_and_region_without_options_has_nothing_to_compare() -> None:
    assert compare("C", Region.NORTH, generated()) == ()


# --- the numbers ------------------------------------------------------------------------


def test_effective_prices_follow_the_promo_economics() -> None:
    outcomes = by_mechanism(compare("A", Region.NORTH, generated()))

    def best(mechanism: Mechanism) -> PlanLine:
        found = outcomes[mechanism].best
        assert found is not None
        return found.option

    pct = outcomes[Mechanism.PCT_OFF].best
    assert pct is not None
    assert pct.effective_price == pytest.approx(100 * (1 - best(Mechanism.PCT_OFF).depth_pct / 100))
    bogo = outcomes[Mechanism.BOGO].best
    assert bogo is not None
    assert bogo.effective_price == 50.0
    fixed = outcomes[Mechanism.FIXED_PRICE].best
    assert fixed is not None
    assert fixed.effective_price == effective_unit_price(
        Mechanism.FIXED_PRICE, 100.0, best(Mechanism.FIXED_PRICE).depth_pct
    )
    assert str(int(fixed.effective_price)).endswith("9")
    bundle = outcomes[Mechanism.BUNDLE].best
    assert bundle is not None
    depth = best(Mechanism.BUNDLE).depth_pct / 100
    # The pair's discount split pro-rata by base price leaves each SKU at depth % off its own.
    assert bundle.effective_price == pytest.approx(100 * (1 - depth))
    assert bundle.partner_effective_price is not None
    assert bundle.partner_effective_price == pytest.approx(50 * (1 - depth))
    assert bundle.effective_price + bundle.partner_effective_price == pytest.approx(
        (100 + 50) * (1 - depth)
    )
    assert pct.partner_effective_price is None
    assert pct.basket_lift is None


def test_each_mechanism_shows_its_best_option_by_value_with_that_options_numbers() -> None:
    context = generated()
    table = context.options.table

    for outcome in compare("A", Region.NORTH, context):
        rows = rows_for(context.options, "A", Region.NORTH, outcome.mechanism)
        best_row = rows[int(np.argmax(table["value"].to_numpy()[rows]))]
        found = outcome.best
        assert found is not None
        assert found.option == context.options.lines[best_row]
        numbers = table.iloc[best_row]
        assert found.value == numbers["value"]
        assert found.units == numbers["units"]
        assert found.revenue == numbers["revenue"]
        assert found.gross_profit == numbers["gross_profit"]
        assert found.margin == numbers["margin"]
        assert found.promo_cost == numbers["promo_cost"]
        assert found.incremental_profit == numbers["incremental_profit"]
        assert found.cannibalised_profit == numbers["cannibalised_profit"]
        assert found.halo_profit == numbers["halo_profit"]
        assert found.clearance_value == numbers["clearance_value"]
        assert outcome.chosen is False


@pytest.mark.parametrize("dominant", [Mechanism.FIXED_PRICE, Mechanism.BOGO, Mechanism.BUNDLE])
def test_a_mechanism_that_clearly_dominates_ranks_first(dominant: Mechanism) -> None:
    context = generated({**NO_EFFECT, dominant: 2.0})

    outcomes = compare("A", Region.NORTH, context)

    assert outcomes[0].mechanism is dominant
    values = [outcome.best.value for outcome in outcomes if outcome.best is not None]
    assert values == sorted(values, reverse=True)


def test_the_comparison_is_deterministic() -> None:
    first = compare("A", Region.SOUTH, generated())
    again = compare("A", Region.SOUTH, generated())

    assert first == again
    assert [outcome.model_dump() for outcome in first] == [
        outcome.model_dump() for outcome in again
    ]


# --- the chosen plan line ---------------------------------------------------------------


def test_the_chosen_plan_line_stands_for_its_mechanism_even_when_it_is_not_its_best() -> None:
    context = generated()
    rows = rows_for(context.options, "A", Region.NORTH, Mechanism.PCT_OFF)
    worst = rows[int(np.argmin(context.options.table["value"].to_numpy()[rows]))]
    chosen = context.options.lines[worst]

    outcomes = by_mechanism(compare("A", Region.NORTH, context, chosen=chosen))

    pct = outcomes[Mechanism.PCT_OFF]
    assert pct.chosen is True
    assert pct.best is not None
    assert pct.best.option == chosen
    assert pct.best.value == context.options.table["value"].iloc[worst]
    assert [outcome.mechanism for outcome in outcomes.values() if outcome.chosen] == [
        Mechanism.PCT_OFF
    ]


def test_a_chosen_line_that_is_not_among_the_options_is_an_error() -> None:
    context = generated()
    stranger = context.options.lines[0].model_copy(update={"start_week": 99})

    with pytest.raises(ValueError, match="not among"):
        compare(stranger.sku_id, stranger.region, context, chosen=stranger)
    with pytest.raises(ValueError, match="SKU and region"):
        compare("D", Region.NORTH, context, chosen=context.options.lines[0])


# --- mechanisms with no option ----------------------------------------------------------


def test_a_mechanism_whose_every_option_breaks_a_rule_is_listed_last_with_why() -> None:
    outcomes = compare("B", Region.NORTH, generated())

    # BOGO sells B at ₹50, below its ₹85 cost, and B is not overstocked (ADR 0007).
    assert outcomes[-1].mechanism is Mechanism.BOGO
    assert outcomes[-1].best is None
    assert outcomes[-1].unavailable == (PruneReason.BELOW_COST,)
    assert all(outcome.best is not None for outcome in outcomes[:-1])
    assert all(outcome.unavailable == () for outcome in outcomes[:-1])


def test_a_mechanism_pruned_for_stock_says_so() -> None:
    outcomes = by_mechanism(
        compare("D", Region.NORTH, generated(inventory=stock(D_North=(1.0, False))))
    )

    assert set(outcomes) == {Mechanism.PCT_OFF, Mechanism.BOGO, Mechanism.FIXED_PRICE}
    for outcome in outcomes.values():
        assert outcome.best is None
        assert PruneReason.STOCK in outcome.unavailable
    # A duplicate charm price is never why a mechanism is unavailable: a shallower depth
    # offered that price and was pruned for its own reason.
    assert PruneReason.DUPLICATE_PRICE not in outcomes[Mechanism.FIXED_PRICE].unavailable
    assert outcomes[Mechanism.FIXED_PRICE].unavailable == (
        PruneReason.MAX_DISCOUNT,
        PruneReason.STOCK,
    )
