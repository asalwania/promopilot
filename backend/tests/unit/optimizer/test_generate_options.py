"""Promo option generation (SPEC §9.3, ADR 0035), on small hand-built contexts.

The fakes pin the demand model's predictions and the detected relations, so each pruning
rule can be checked by hand.
"""

from collections.abc import Iterable, Sequence
from dataclasses import replace
from typing import Any

import numpy as np
import pandas as pd
import pytest

from promopilot.competitors import CompetitorGap, CompetitorGaps
from promopilot.domain import (
    CompanyPolicy,
    Mechanism,
    PlanLine,
    PlanningRequest,
    PromoWindow,
    Region,
    Scope,
    Segment,
    TargetSegment,
)
from promopilot.economics import effective_unit_price
from promopilot.models.demand import OPTION_COLUMNS, DemandModel, Prediction, PredictionContext
from promopilot.models.relations import (
    Relations,
    line_effect_totals,
    pairwise_cannibalisations,
)
from promopilot.optimizer import (
    P90_Z,
    FittedOptionFacts,
    OptionContext,
    PriceMatch,
    PromoOptions,
    PruneReason,
    generate_options,
)
from tests.conftest import SMALL_AS_OF

SEGMENTS = [segment.value for segment in Segment]
PRODUCTS = pd.DataFrame(
    {
        "sku_id": ["A", "B", "C", "D"],
        "category": ["Snacks", "Snacks", "Beverages", "Snacks"],
        "base_price": [100.0, 100.0, 50.0, 60.0],
        "unit_cost": [40.0, 85.0, 30.0, 20.0],
    }
)
PRICES = dict(zip(PRODUCTS["sku_id"], PRODUCTS["base_price"], strict=True))
COSTS = dict(zip(PRODUCTS["sku_id"], PRODUCTS["unit_cost"], strict=True))
WINDOW = PromoWindow(start_week=60, end_week=63)
PLENTY = 1_000_000.0


def request(**changes: Any) -> PlanningRequest:
    fields: dict[str, Any] = {
        "as_of_week": 58,
        "scope": Scope(regions=(Region.NORTH, Region.SOUTH), categories=("Snacks",)),
        "promo_window": WINDOW,
        "marketing_budget": 500_000.0,
    }
    return PlanningRequest.model_validate(fields | changes)


class FakeRelations:
    """A and B are substitutes; C is A's complement (in another category)."""

    def substitutes(self, sku_id: str) -> pd.DataFrame:
        partner = {"A": "B", "B": "A"}.get(sku_id)
        rows = [] if partner is None else [{"sku_id": partner, "theta": 0.5}]
        frame = pd.DataFrame(rows, columns=["sku_id", "theta"])
        return frame.assign(std_error=0.05, q_value=0.001)

    def complements(self, sku_id: str) -> pd.DataFrame:
        partner = {"A": "C", "C": "A"}.get(sku_id)
        rows = [] if partner is None else [{"sku_id": partner, "theta": -0.4}]
        frame = pd.DataFrame(rows, columns=["sku_id", "theta"])
        return frame.assign(lift=2.0, support=0.01, std_error=0.05)


class FakeDemand:
    """100 baseline units a week; a promotion lifts them by 2 x depth (All customers) or
    0.5 x depth (one segment); std is a tenth of the units. Records what it predicts."""

    def __init__(self) -> None:
        self.predicted: list[PlanLine] = []

    def predict(self, options: Sequence[PlanLine], context: PredictionContext) -> Prediction:
        self.predicted += options
        rows = []
        for line in options:
            lift = 2.0 if line.target_segment is TargetSegment.ALL_CUSTOMERS else 0.5
            baseline = 100.0 * line.duration_weeks
            units = baseline * (1 + lift * line.depth_pct / 100)
            price = effective_unit_price(line.mechanism, PRICES[line.sku_id], line.depth_pct)
            partner = line.bundle_partner_sku_id is not None
            rows.append(
                {
                    "units": units,
                    "units_std": units / 10,
                    "baseline_units": baseline,
                    "pull_forward_units": 0.0,
                    "incremental_units": units - baseline,
                    "revenue": units * price,
                    "gross_profit": units * (price - COSTS[line.sku_id]),
                    "margin": (price - COSTS[line.sku_id]) / price,
                    "promo_cost": units * (PRICES[line.sku_id] - price) + 1000.0,
                    "incremental_profit": units * (price - COSTS[line.sku_id]) - 5000.0,
                    "anchor_discount_funding": units * (PRICES[line.sku_id] - price),
                    "partner_units": 60.0 * line.duration_weeks if partner else 0.0,
                    "partner_units_std": 6.0 * line.duration_weeks if partner else 0.0,
                    "partner_baseline_units": 40.0 * line.duration_weeks if partner else 0.0,
                    "partner_discount_funding": 7.0 if partner else 0.0,
                }
            )
        return Prediction(
            options=pd.DataFrame(rows, columns=OPTION_COLUMNS),
            segments=pd.DataFrame(),
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
        rows = [
            {"week_id": w, "store_id": r, "sku_id": k, "segment": g, "units": 10.0}
            for w in weeks
            for r in regions or ["North", "South"]
            for k in sku_ids or PRODUCTS["sku_id"]
            for g in SEGMENTS
        ]
        return pd.DataFrame(rows)


def stock(**overrides: tuple[float, bool]) -> pd.DataFrame:
    """Available stock and overstock flag per SKU and region; `A_North=(700, False)`."""
    rows = []
    for sku_id in PRODUCTS["sku_id"]:
        for region in ("North", "South"):
            available, overstocked = overrides.get(f"{sku_id}_{region}", (PLENTY, False))
            rows.append(
                {
                    "sku_id": sku_id,
                    "region": region,
                    "available_stock": available,
                    "is_overstock": overstocked,
                }
            )
    return pd.DataFrame(rows)


def context(
    demand: FakeDemand | None = None,
    inventory: pd.DataFrame | None = None,
    policy: CompanyPolicy | None = None,
) -> OptionContext:
    return OptionContext(
        demand_model=demand or FakeDemand(),
        relations=FakeRelations(),
        products=PRODUCTS,
        stock=stock() if inventory is None else inventory,
        policy=policy or CompanyPolicy(),
    )


def lines_of(options: PromoOptions, **match: Any) -> list[PlanLine]:
    return [
        line
        for line in options.lines
        if all(getattr(line, name) == value for name, value in match.items())
    ]


def rows_of(options: PromoOptions, **match: Any) -> pd.DataFrame:
    keep = [
        all(getattr(line, name) == value for name, value in match.items()) for line in options.lines
    ]
    return options.table[keep]


# --- enumeration -----------------------------------------------------------------------


def test_every_option_starts_and_ends_inside_the_promo_window() -> None:
    options = generate_options(request(), context())

    assert options.lines
    for line in options.lines:
        assert line.start_week >= WINDOW.start_week
        assert line.start_week + line.duration_weeks - 1 <= WINDOW.end_week
    # A four-week window fits every duration, at every start week that fits it.
    timings = {(line.start_week, line.duration_weeks) for line in lines_of(options, sku_id="A")}
    assert timings == {
        (start, duration) for duration in (1, 2, 3, 4) for start in range(60, 64 - duration + 1)
    }


def test_short_windows_only_get_the_durations_that_fit() -> None:
    window = PromoWindow(start_week=60, end_week=61)

    options = generate_options(request(promo_window=window), context())

    assert {(line.start_week, line.duration_weeks) for line in options.lines} == {
        (60, 1),
        (61, 1),
        (60, 2),
    }


def test_both_segment_targeted_and_all_customers_options_are_present() -> None:
    options = generate_options(request(), context())

    assert {line.target_segment for line in lines_of(options, sku_id="A")} == set(TargetSegment)


def test_each_mechanism_gets_its_own_depths() -> None:
    options = generate_options(request(), context())

    def depths(mechanism: Mechanism) -> set[int]:
        return {line.depth_pct for line in lines_of(options, sku_id="A", mechanism=mechanism)}

    assert depths(Mechanism.PCT_OFF) == {5, 10, 15, 20, 25, 30, 40, 50}
    assert depths(Mechanism.BOGO) == {50}
    assert depths(Mechanism.BUNDLE) == {10, 15, 20, 25}
    # FIXED_PRICE starts from every level too, and keeps one per charm price: on A's ₹100,
    # ₹89 (5-10%), ₹79 (15-20%), ₹69 (25-30%) and ₹59 (40%); ₹49 at 50% is 51% off.
    assert depths(Mechanism.FIXED_PRICE) == {5, 15, 25, 40}


def test_only_the_scopes_skus_and_regions_are_enumerated() -> None:
    options = generate_options(request(), context())

    assert {line.sku_id for line in options.lines} == {"A", "B", "D"}
    assert {line.region for line in options.lines} == {Region.NORTH, Region.SOUTH}
    narrowed = request(scope=Scope(regions=(Region.SOUTH,), categories=("Snacks",), sku_ids=("A",)))
    assert {(line.sku_id, line.region) for line in generate_options(narrowed, context()).lines} == {
        ("A", Region.SOUTH)
    }


def test_the_planner_can_narrow_mechanisms_segments_and_skus() -> None:
    options = generate_options(
        request(),
        context(),
        mechanisms=[Mechanism.BOGO],
        target_segments=[TargetSegment.FAMILIES],
        sku_ids=["D"],
    )

    assert {(line.sku_id, line.mechanism, line.target_segment) for line in options.lines} == {
        ("D", Mechanism.BOGO, TargetSegment.FAMILIES)
    }
    with pytest.raises(ValueError, match="C"):
        generate_options(request(), context(), sku_ids=["C"])


# --- bundles ---------------------------------------------------------------------------


def test_a_bundle_appears_only_with_a_detected_complement_even_outside_the_scope() -> None:
    options = generate_options(request(), context())

    bundles = lines_of(options, mechanism=Mechanism.BUNDLE)
    assert bundles
    # A's only complement is C, a Beverages SKU outside the Snacks scope (ADR 0014).
    assert {(line.sku_id, line.bundle_partner_sku_id) for line in bundles} == {("A", "C")}


def test_a_bundle_is_pruned_when_its_partners_p90_exceeds_the_partners_stock() -> None:
    # C's P90 over a week is 60 + 1.2816 x 6 = 67.7 units, and 135.4 over two.
    inventory = stock(C_North=(100.0, False))

    options = generate_options(request(), context(inventory=inventory))

    north = lines_of(options, mechanism=Mechanism.BUNDLE, region=Region.NORTH)
    assert {line.duration_weeks for line in north} == {1}
    assert lines_of(options, mechanism=Mechanism.BUNDLE, region=Region.SOUTH, duration_weeks=4)
    assert options.pruned[PruneReason.PARTNER_STOCK] == 4 * 5 * (3 + 2 + 1)
    kept = rows_of(options, mechanism=Mechanism.BUNDLE)
    assert (kept["partner_p90_units"] <= kept["partner_available_stock"]).all()


def test_a_bundles_discount_funding_is_reported_per_sku() -> None:
    options = generate_options(request(), context())

    bundle = rows_of(options, mechanism=Mechanism.BUNDLE).iloc[0]
    assert bundle["partner_discount_funding"] == 7.0
    assert bundle["anchor_discount_funding"] > 0
    single = rows_of(options, mechanism=Mechanism.PCT_OFF).iloc[0]
    assert single["partner_discount_funding"] == 0


# --- pruning ---------------------------------------------------------------------------


def test_options_below_unit_cost_are_pruned_before_they_are_predicted() -> None:
    demand = FakeDemand()

    options = generate_options(request(), context(demand))

    # B costs ₹85 of its ₹100: 15% off still covers it, 20% off does not.
    assert {
        line.depth_pct for line in lines_of(options, sku_id="B", mechanism=Mechanism.PCT_OFF)
    } == {
        5,
        10,
        15,
    }
    assert not lines_of(options, sku_id="B", mechanism=Mechanism.BOGO)
    assert options.pruned[PruneReason.BELOW_COST] > 0
    assert all(line.sku_id != "B" or line.depth_pct <= 15 for line in demand.predicted)


def test_an_overstocked_sku_may_sell_below_unit_cost() -> None:
    options = generate_options(request(), context(inventory=stock(B_North=(PLENTY, True))))

    north = lines_of(options, sku_id="B", mechanism=Mechanism.PCT_OFF, region=Region.NORTH)
    south = lines_of(options, sku_id="B", mechanism=Mechanism.PCT_OFF, region=Region.SOUTH)
    assert {line.depth_pct for line in north} == {5, 10, 15, 20, 25, 30, 40, 50}
    assert {line.depth_pct for line in south} == {5, 10, 15}


def test_options_deeper_than_the_policy_maximum_are_pruned_on_their_effective_discount() -> None:
    options = generate_options(request(), context(policy=CompanyPolicy(max_discount_pct=30)))

    for line in options.lines:
        price = effective_unit_price(line.mechanism, PRICES[line.sku_id], line.depth_pct)
        assert 1 - price / PRICES[line.sku_id] <= 0.30 + 1e-9
    assert not lines_of(options, mechanism=Mechanism.BOGO)
    # ₹69 is 31% off A's ₹100, so FIXED_PRICE at 30% goes too (ADR 0015).
    assert max(line.depth_pct for line in lines_of(options, mechanism=Mechanism.FIXED_PRICE)) < 30
    assert options.pruned[PruneReason.MAX_DISCOUNT] > 0


def test_fixed_price_depths_that_land_on_the_same_charm_price_are_kept_once() -> None:
    options = generate_options(request(), context(), sku_ids=["D"])

    # On D's ₹60: 5-15% all give ₹49 and 20-30% all give ₹39; ₹29 is 52% off.
    fixed = lines_of(options, mechanism=Mechanism.FIXED_PRICE)
    assert {line.depth_pct for line in fixed} == {5, 20}
    per_price_level = 2 * 10 * 5  # regions x timings x targets
    assert options.pruned[PruneReason.DUPLICATE_PRICE] == 4 * per_price_level


def test_options_whose_p90_units_exceed_available_stock_are_pruned() -> None:
    options = generate_options(request(), context(inventory=stock(A_North=(700.0, False))))

    kept = rows_of(options, sku_id="A", region=Region.NORTH)
    assert not kept.empty
    assert (kept["p90_units"] <= 700.0).all()
    assert kept["p90_units"].to_numpy() == pytest.approx(
        (kept["units"] + P90_Z * kept["units_std"]).to_numpy()
    )
    assert (kept["available_stock"] == 700.0).all()
    assert options.pruned[PruneReason.STOCK] > 0
    # South has plenty: its four-week, 50%-off All-customers option survives.
    assert lines_of(
        options,
        sku_id="A",
        region=Region.SOUTH,
        mechanism=Mechanism.PCT_OFF,
        depth_pct=50,
        duration_weeks=4,
        target_segment=TargetSegment.ALL_CUSTOMERS,
    )


def test_every_enumerated_option_is_kept_or_counted_under_one_reason() -> None:
    options = generate_options(
        request(), context(inventory=stock(A_North=(700.0, False), C_South=(100.0, False)))
    )

    assert set(options.pruned) == set(PruneReason)
    assert options.enumerated == len(options.lines) + sum(options.pruned.values())
    assert len(options.table) == len(options.lines)


# --- predictions and effects -----------------------------------------------------------


def test_options_carry_predictions_effects_and_clearance_value() -> None:
    policy = CompanyPolicy()
    options = generate_options(
        request(), context(inventory=stock(D_North=(PLENTY, True)), policy=policy)
    )

    table = options.table
    effects = line_effect_totals(list(options.lines), FakeRelations(), FakeDemand(), PRODUCTS)
    assert table["cannibalised_profit"].to_numpy() == pytest.approx(
        effects["cannibalised_profit"].to_numpy()
    )
    assert table["halo_profit"].to_numpy() == pytest.approx(effects["halo_profit"].to_numpy())
    assert (table.loc[rows_of(options, sku_id="A").index, "cannibalised_profit"] > 0).all()
    # Clearance value only where the SKU is overstocked in the line's region (ADR 0005).
    overstocked = rows_of(options, sku_id="D", region=Region.NORTH)
    assert overstocked["clearance_value"].to_numpy() == pytest.approx(
        ((overstocked["units"] - overstocked["baseline_units"]) * 20.0 * 0.30).to_numpy()
    )
    assert (rows_of(options, sku_id="D", region=Region.SOUTH)["clearance_value"] == 0).all()
    assert table["value"].to_numpy() == pytest.approx(
        (
            table["incremental_profit"]
            - table["cannibalised_profit"]
            + table["halo_profit"]
            + table["clearance_value"]
        ).to_numpy()
    )


def test_a_bundle_partner_that_is_overstocked_adds_its_own_clearance_value() -> None:
    options = generate_options(request(), context(inventory=stock(C_North=(PLENTY, True))))

    bundle = rows_of(options, mechanism=Mechanism.BUNDLE, region=Region.NORTH, duration_weeks=1)
    # A is not overstocked; C sells 60 against a 40 baseline, at a ₹30 unit cost.
    assert bundle["clearance_value"].to_numpy() == pytest.approx(
        np.full(len(bundle), 20 * 30 * 0.3)
    )


def test_no_options_survive_an_empty_scope() -> None:
    options = generate_options(request(), context(), mechanisms=[Mechanism.BUNDLE], sku_ids=["B"])

    assert options.lines == ()
    assert options.table.empty
    assert options.enumerated == 0


# --- on a fitted world -----------------------------------------------------------------


def test_the_fitted_models_generate_options_deterministically(
    small_models: tuple[DemandModel, Relations], small_history: Any, small_dataset: Any
) -> None:
    model, found = small_models
    products = small_history.products
    category = str(products["category"].iloc[0])
    inventory = small_dataset.inventory
    snapshot = inventory[inventory["snapshot_week"] == SMALL_AS_OF - 1].merge(
        small_history.stores[["store_id", "region"]], on="store_id"
    )
    pooled = snapshot.groupby(["sku_id", "region"], as_index=False)[
        ["on_hand", "safety_stock"]
    ].sum()
    pooled = pooled.assign(
        available_stock=pooled["on_hand"] - pooled["safety_stock"], is_overstock=False
    )
    fitted = OptionContext(
        demand_model=model,
        relations=found,
        products=products,
        stock=pooled[["sku_id", "region", "available_stock", "is_overstock"]],
        policy=CompanyPolicy(),
    )
    planning = request(
        as_of_week=SMALL_AS_OF,
        scope=Scope(regions=(Region.NORTH,), categories=(category,)),
        promo_window=PromoWindow(start_week=SMALL_AS_OF + 1, end_week=SMALL_AS_OF + 2),
    )

    first = generate_options(planning, fitted)
    again = generate_options(planning, fitted)

    assert len(first.lines) > 100
    assert first.lines == again.lines
    pd.testing.assert_frame_equal(first.table, again.table)
    assert first.table.notna().all().all()
    # The facts the optimiser reads come from the same context and fitted models.
    facts = FittedOptionFacts(fitted)
    anchor = first.lines[0]
    sku = facts.sku(anchor.sku_id, anchor.region)
    assert sku.category == category
    assert sku.overstocked is False
    pairs = [(first.lines[0], line) for line in first.lines[1:40]]
    pairwise = pairwise_cannibalisations(pairs, found, model, products, PredictionContext())
    assert list(facts.pairwise_cannibalisation(pairs)) == pytest.approx(list(pairwise))


def test_the_optimisers_facts_name_each_skus_category_prices_and_overstock() -> None:
    facts = FittedOptionFacts(context(inventory=stock(D_South=(500.0, True))))

    d = facts.sku("D", Region.SOUTH)
    assert (d.category, d.base_price, d.unit_cost, d.overstocked) == ("Snacks", 60.0, 20.0, True)
    assert facts.sku("D", Region.NORTH).overstocked is False
    assert facts.sku("C", Region.NORTH).category == "Beverages"


def test_the_reasons_each_mechanism_lost_options_for_are_recorded() -> None:
    options = generate_options(request(), context(inventory=stock(D_North=(1.0, False))))

    pruned_by = options.pruned_by_mechanism
    # B costs ₹85: BOGO's ₹50 and PCT_OFF from 20% off sell below it (ADR 0007).
    assert pruned_by["B", Region.NORTH, Mechanism.BOGO] == {PruneReason.BELOW_COST}
    assert pruned_by["B", Region.NORTH, Mechanism.PCT_OFF] == {PruneReason.BELOW_COST}
    # D has no stock in North: whatever passed the price rules went for stock.
    assert pruned_by["D", Region.NORTH, Mechanism.PCT_OFF] == {PruneReason.STOCK}
    assert pruned_by["D", Region.NORTH, Mechanism.FIXED_PRICE] == {
        PruneReason.MAX_DISCOUNT,
        PruneReason.DUPLICATE_PRICE,
        PruneReason.STOCK,
    }
    assert ("A", Region.NORTH, Mechanism.PCT_OFF) not in pruned_by


# --- clearance targets and price matches (ADR 0040) ------------------------------------------


class PathDemand(FakeDemand):
    """FakeDemand, broken down per week: the anchor's promo units spread evenly over its promo
    weeks against 100 baseline units a week, then a 20-unit pull-forward dip in the week
    after; a BUNDLE partner sells 60 a week against 40."""

    def line_paths(self, options: Sequence[PlanLine], context: PredictionContext) -> pd.DataFrame:
        units = self.predict(options, context).options["units"]
        rows = []
        for n, line in enumerate(options):
            weeks = range(line.start_week, line.start_week + line.duration_weeks)
            for week in weeks:
                rows.append((n, week, line.sku_id, units[n] / line.duration_weeks, 100.0))
                if line.bundle_partner_sku_id is not None:
                    rows.append((n, week, line.bundle_partner_sku_id, 60.0, 40.0))
            rows.append((n, weeks.stop, line.sku_id, 80.0, 100.0))
        columns = ["option", "week_id", "sku_id", "units", "baseline_units"]
        return pd.DataFrame(rows, columns=columns).assign(segment="Families", price=1.0)


def cleared(*sku_ids: str, sell_through: float = 0.5) -> list[dict[str, Any]]:
    return [{"sku_id": sku_id, "sell_through": sell_through} for sku_id in sku_ids]


def test_a_sku_the_brief_names_for_clearance_is_overstocked_in_every_scope_region() -> None:
    options = generate_options(request(clearance_targets=cleared("B")), context(PathDemand()))

    for region in (Region.NORTH, Region.SOUTH):
        depths = {
            line.depth_pct
            for line in lines_of(options, sku_id="B", mechanism=Mechanism.PCT_OFF, region=region)
        }
        assert depths == {5, 10, 15, 20, 25, 30, 40, 50}
        assert (rows_of(options, sku_id="B", region=region)["clearance_value"] > 0).all()


def test_a_clearance_target_outside_the_scope_is_rejected() -> None:
    with pytest.raises(ValueError, match=r"clearance target.*C"):
        generate_options(request(clearance_targets=cleared("C")), context(PathDemand()))


def test_options_of_a_clearance_sku_carry_their_uplift_over_the_promo_window() -> None:
    options = generate_options(request(clearance_targets=cleared("D")), context(PathDemand()))

    early = rows_of(options, sku_id="D", start_week=60, duration_weeks=1)
    # The dip in week 61 is inside the window: uplift = units - 100 - 20.
    assert early["window_uplift"].to_numpy() == pytest.approx((early["units"] - 120).to_numpy())
    late = rows_of(options, sku_id="D", start_week=63, duration_weeks=1)
    # The dip in week 64 falls after the window.
    assert late["window_uplift"].to_numpy() == pytest.approx((late["units"] - 100).to_numpy())
    assert (rows_of(options, sku_id="A")["window_uplift"] == 0).all()
    # Available stock, and the model's own baseline over the four window weeks (4 x 100).
    found = {(c.sku_id, c.region, c.available_stock, c.baseline_units) for c in options.clearance}
    assert found == {
        ("D", Region.NORTH, PLENTY, 400.0),
        ("D", Region.SOUTH, PLENTY, 400.0),
    }


def test_a_bundle_partner_with_a_clearance_target_carries_its_own_window_uplift() -> None:
    planning = request(
        scope=Scope(regions=(Region.NORTH,), categories=("Snacks", "Beverages")),
        clearance_targets=cleared("C"),
    )

    options = generate_options(planning, context(PathDemand()), sku_ids=["A", "C"])

    bundle = rows_of(
        options, sku_id="A", mechanism=Mechanism.BUNDLE, duration_weeks=2, start_week=60
    )
    assert not bundle.empty
    assert (bundle["partner_window_uplift"] == 40.0).all()
    single = rows_of(options, sku_id="A", mechanism=Mechanism.PCT_OFF)
    assert (single["partner_window_uplift"] == 0).all()


def test_a_clearance_target_skips_a_region_with_no_available_stock() -> None:
    inventory = stock(D_South=(0.0, False))

    options = generate_options(
        request(clearance_targets=cleared("D")), context(PathDemand(), inventory)
    )

    assert [(c.sku_id, c.region) for c in options.clearance] == [("D", Region.NORTH)]


def gaps(*rows: tuple[str, Region, float, bool]) -> CompetitorGaps:
    """(SKU, region, competitor price, KVI) rows against the catalogue's base prices."""
    policy = CompanyPolicy()
    found = []
    for sku_id, region, competitor_price, is_kvi in rows:
        cpi = competitor_price / PRICES[sku_id]
        found.append(
            CompetitorGap(
                region=region,
                sku_id=sku_id,
                name=sku_id,
                category="Snacks",
                subcategory="Namkeen",
                is_kvi=is_kvi,
                base_price=PRICES[sku_id],
                competitor_price=competitor_price,
                competitor_on_promo=False,
                price_week=57,
                cpi=cpi,
                gap=1 - cpi,
                undercut=is_kvi and cpi < 1 - policy.undercut_threshold,
            )
        )
    return CompetitorGaps(
        as_of_week=58,
        undercut_threshold=policy.undercut_threshold,
        kvi_price_tolerance=policy.kvi_price_tolerance,
        gaps=tuple(found),
    )


GRID = {5, 10, 15, 20, 25, 30, 40, 50}


def test_an_undercut_kvi_gets_a_price_match_option_in_its_region() -> None:
    # The competitor sells A at ₹87.50 in the North: 13% off (₹87) is the smallest match.
    found = gaps(("A", Region.NORTH, 87.5, True), ("D", Region.NORTH, 30.0, False))
    options = generate_options(request(), replace(context(), competitor_gaps=found))

    matched = lines_of(options, sku_id="A", mechanism=Mechanism.PCT_OFF, depth_pct=13)
    assert {line.region for line in matched} == {Region.NORTH}
    assert {line.target_segment for line in matched} == set(TargetSegment)
    assert options.price_matches == (
        PriceMatch(sku_id="A", region=Region.NORTH, depth_pct=13, competitor_price=87.5),
    )
    # D is not a KVI: no match, however wide its gap.
    d_depths = {
        line.depth_pct for line in lines_of(options, sku_id="D", mechanism=Mechanism.PCT_OFF)
    }
    assert d_depths <= GRID


def test_a_price_match_on_a_grid_depth_adds_no_option() -> None:
    found = gaps(("A", Region.NORTH, 90.0, True))

    options = generate_options(request(), replace(context(), competitor_gaps=found))

    assert options.price_matches == (
        PriceMatch(sku_id="A", region=Region.NORTH, depth_pct=10, competitor_price=90.0),
    )
    assert options.enumerated == generate_options(request(), context()).enumerated


def test_the_optimisers_facts_name_each_kvis_competitor_price() -> None:
    found = gaps(("A", Region.NORTH, 87.5, True))
    facts = FittedOptionFacts(replace(context(), competitor_gaps=found))

    north, south = facts.sku("A", Region.NORTH), facts.sku("A", Region.SOUTH)
    assert (north.is_kvi, north.competitor_price) == (True, 87.5)
    assert (south.is_kvi, south.competitor_price) == (False, None)
