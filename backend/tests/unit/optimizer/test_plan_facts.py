"""The plan facts of a selection of promo options: what `validate_plan` reads (ADR 0028)."""

import pytest

from promopilot.domain import Mechanism, Region, Scope
from promopilot.optimizer import FittedOptionFacts, generate_options, plan_facts
from tests.unit.optimizer.test_generate_options import PathDemand, cleared, context, request


def test_each_selected_option_carries_its_own_numbers_and_sku_facts() -> None:
    planning = request(scope=Scope(regions=(Region.NORTH,), categories=("Snacks", "Beverages")))
    fitted = context(PathDemand())
    options = generate_options(planning, fitted)
    bundle = next(n for n, line in enumerate(options.lines) if line.mechanism is Mechanism.BUNDLE)
    single = next(n for n, line in enumerate(options.lines) if line.mechanism is Mechanism.PCT_OFF)
    facts = FittedOptionFacts(fitted)

    plan = plan_facts(options, [single, bundle], facts)

    assert [fact.line for fact in plan.lines] == [options.lines[single], options.lines[bundle]]
    for fact, row in zip(plan.lines, [single, bundle], strict=True):
        numbers = options.table.iloc[row]
        assert fact.anchor == facts.sku(fact.line.sku_id, fact.line.region)
        assert fact.expected_units == pytest.approx(numbers["units"])
        assert fact.p90_units == pytest.approx(numbers["p90_units"])
        assert fact.available_stock == pytest.approx(numbers["available_stock"])
        assert fact.expected_revenue == pytest.approx(numbers["revenue"])
        assert fact.expected_gross_profit == pytest.approx(numbers["gross_profit"])
        assert fact.promo_cost == pytest.approx(numbers["promo_cost"])
    single_fact, bundle_fact = plan.lines
    assert single_fact.partner is None
    partner = options.lines[bundle].bundle_partner_sku_id
    assert partner is not None
    assert bundle_fact.partner == facts.sku(partner, Region.NORTH)
    assert plan.clearance == ()


def test_a_clearance_target_expects_its_baseline_plus_the_window_uplift_of_its_lines() -> None:
    planning = request(
        scope=Scope(regions=(Region.NORTH,), categories=("Snacks", "Beverages")),
        clearance_targets=cleared("C"),
    )
    fitted = context(PathDemand())
    options = generate_options(planning, fitted, sku_ids=["A", "C"])
    rows = [
        n
        for n, line in enumerate(options.lines)
        if line.mechanism is Mechanism.BUNDLE and line.bundle_partner_sku_id == "C"
    ][:1]
    assert rows

    plan = plan_facts(options, rows, FittedOptionFacts(fitted))

    [target] = options.clearance
    [fact] = plan.clearance
    assert (fact.sku_id, fact.region, fact.available_stock) == (
        "C",
        Region.NORTH,
        target.available_stock,
    )
    uplift = float(options.table["partner_window_uplift"].iloc[rows[0]])
    assert uplift > 0
    assert fact.expected_units == pytest.approx(target.baseline_units + uplift)
