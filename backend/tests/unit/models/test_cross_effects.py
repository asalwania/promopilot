"""Cannibalisation and halo per plan line (SPEC §9.2, ADR 0005, ADR 0033): hand-computed cases.

The fakes pin every input the calculators read (the detected relations, the no-promotion
baseline, a line's own predicted units) so each expected number is worked out by hand.
"""

import math
from collections.abc import Hashable, Iterable, Sequence
from typing import Any

import numpy as np
import pandas as pd
import pytest

from promopilot.domain import Mechanism, PlanLine, Region, Segment, TargetSegment
from promopilot.models.demand import DemandHistory, DemandModel, PredictionContext
from promopilot.models.relations import (
    EFFECT_COLUMNS,
    Relations,
    line_effects,
    pairwise_cannibalisation,
)
from tests.conftest import SMALL_AS_OF

SEGMENTS = [segment.value for segment in Segment]
STORES = {"North": ["N1", "N2"], "South": ["S1"]}
STORE_UNITS = {"North": 10.0, "South": 4.0}
"""Baseline units per store, SKU, segment and week."""

PRODUCTS = pd.DataFrame(
    {
        "sku_id": ["A", "B", "C", "D", "E"],
        "base_price": [100.0, 50.0, 40.0, 80.0, 60.0],
        "unit_cost": [60.0, 30.0, 25.0, 50.0, 40.0],
    }
)
BASE_PRICES = dict(zip(PRODUCTS["sku_id"], PRODUCTS["base_price"], strict=True))
THETA = {("A", "B"): 0.5, ("A", "E"): 0.3, ("B", "E"): 0.2, ("A", "C"): -0.4, ("A", "D"): -0.2}
"""Detected relations: A-B, A-E and B-E substitutes, A-C a complement. A-D is a complement
by lift alone (theta not estimable), so it has no number."""
SUBSTITUTES = {("A", "B"), ("A", "E"), ("B", "E")}


class FakeRelations:
    def substitutes(self, sku_id: str) -> pd.DataFrame:
        return self._partners(sku_id, substitute=True)[["sku_id", "theta", "std_error", "q_value"]]

    def complements(self, sku_id: str) -> pd.DataFrame:
        partners = self._partners(sku_id, substitute=False)
        partners.loc[partners["sku_id"] == ("D" if sku_id == "A" else ""), "theta"] = np.nan
        return partners[["sku_id", "lift", "support", "theta", "std_error"]]

    @staticmethod
    def _partners(sku_id: str, *, substitute: bool) -> pd.DataFrame:
        rows = [
            {"sku_id": b if a == sku_id else a, "theta": theta}
            for (a, b), theta in THETA.items()
            if sku_id in (a, b) and ((a, b) in SUBSTITUTES) == substitute
        ]
        frame = pd.DataFrame(rows, columns=["sku_id", "theta"])
        return frame.assign(std_error=0.05, q_value=0.001, lift=2.0, support=0.01)


class FakeDemand:
    """A flat baseline, and a line's own SKUs selling `LIFT` times baseline at its price."""

    LIFT = 1.5

    def baseline(
        self,
        weeks: Iterable[int],
        *,
        regions: Sequence[str] | None = None,
        store_ids: Sequence[str] | None = None,
        sku_ids: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        rows = [
            {"week_id": w, "store_id": s, "sku_id": k, "segment": g, "units": STORE_UNITS[r]}
            for w in weeks
            for r in regions or STORES
            for s in STORES[r]
            for k in sku_ids or PRODUCTS["sku_id"]
            for g in SEGMENTS
        ]
        return pd.DataFrame(rows)

    def line_paths(self, options: Sequence[PlanLine], context: PredictionContext) -> pd.DataFrame:
        rows = []
        for n, line in enumerate(options):
            stores = len(STORES[line.region.value])
            for sku_id in line.skus:
                base = BASE_PRICES[sku_id]
                for week in range(line.start_week, line.start_week + line.duration_weeks):
                    for segment in SEGMENTS:
                        targeted = line.target_segment in (TargetSegment.ALL_CUSTOMERS, segment)
                        units = STORE_UNITS[line.region.value] * stores
                        rows.append(
                            {
                                "option": n,
                                "week_id": week,
                                "sku_id": sku_id,
                                "segment": segment,
                                "units": units * (self.LIFT if targeted else 1.0),
                                "baseline_units": units,
                                "price": base * (1 - line.depth_pct / 100) if targeted else base,
                            }
                        )
        return pd.DataFrame(rows)


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


def effects_of(*lines: PlanLine) -> pd.DataFrame:
    return line_effects(list(lines), FakeRelations(), FakeDemand(), PRODUCTS)


def row(effects: pd.DataFrame, sku_id: str, n: int = 0) -> dict[Hashable, Any]:
    [record] = effects[(effects["line"] == n) & (effects["sku_id"] == sku_id)].to_dict("records")
    return record


# --- line effects ----------------------------------------------------------------------


def test_a_line_cannibalises_every_substitute_in_its_region_in_scope_or_not() -> None:
    effects = effects_of(line("A"))

    # B: 2 North stores x 10 units x 4 segments x 2 weeks = 160 baseline units; A at 80% of
    # its base price moves them by 0.8 ** 0.5 - 1, each at B's base margin of 20.
    b = row(effects, "B")
    change = 160 * (0.8**0.5 - 1)
    assert b["relation"] == "substitute"
    assert b["region"] == "North"
    assert b["baseline_units"] == pytest.approx(160)
    assert b["units_change"] == pytest.approx(change)
    assert b["units_change_pct"] == pytest.approx(100 * (0.8**0.5 - 1))
    assert b["profit_change"] == pytest.approx(change * 20)
    assert b["cannibalised_profit"] == pytest.approx(-change * 20)
    assert b["halo_profit"] == 0
    # No scope is passed: E is cannibalised just as B is (ADR 0005).
    assert row(effects, "E")["profit_change"] == pytest.approx(160 * (0.8**0.3 - 1) * 20)


def test_a_line_lifts_a_complement_in_its_region_and_counts_it_as_halo() -> None:
    c = row(effects_of(line("A")), "C")

    change = 160 * (0.8**-0.4 - 1)
    assert c["relation"] == "complement"
    assert c["units_change"] == pytest.approx(change)
    assert c["halo_profit"] == pytest.approx(change * 15)
    assert c["cannibalised_profit"] == 0


def test_a_line_has_no_effect_in_another_region() -> None:
    effects = effects_of(line("A", region=Region.SOUTH))

    assert set(effects["region"]) == {"South"}
    # South's own baseline (1 store x 4 units) is the only one used.
    assert row(effects, "B")["baseline_units"] == pytest.approx(1 * 4 * 4 * 2)
    assert row(effects, "B")["units_change"] == pytest.approx(32 * (0.8**0.5 - 1))


def test_a_segment_exclusive_line_moves_only_its_segment() -> None:
    b = row(effects_of(line("A", target_segment=TargetSegment.FAMILIES)), "B")

    # One of four segments moves; the percentage is of B's whole regional baseline.
    assert b["baseline_units"] == pytest.approx(160)
    assert b["units_change"] == pytest.approx(40 * (0.8**0.5 - 1))
    assert b["units_change_pct"] == pytest.approx(25 * (0.8**0.5 - 1))


def test_a_complement_without_an_estimable_theta_has_no_number() -> None:
    assert "D" not in set(effects_of(line("A"))["sku_id"])


def test_a_bundle_moves_others_by_both_prices_and_not_its_own_partner() -> None:
    effects = effects_of(line("B", mechanism=Mechanism.BUNDLE, bundle_partner_sku_id="E"))

    # A is a substitute of both B and E: both prices are 80% of base.
    a = row(effects, "A")
    assert a["units_change"] == pytest.approx(160 * (math.exp((0.5 + 0.3) * math.log(0.8)) - 1))
    assert "E" not in set(effects["sku_id"])
    assert "B" not in set(effects["sku_id"])


def test_effects_come_one_row_per_line_and_affected_sku() -> None:
    effects = effects_of(line("A"), line("B", region=Region.SOUTH))

    assert list(effects.columns) == EFFECT_COLUMNS
    assert sorted(effects.loc[effects["line"] == 0, "sku_id"]) == ["B", "C", "E"]
    assert sorted(effects.loc[effects["line"] == 1, "sku_id"]) == ["A", "E"]
    assert effects_of().empty


# --- pairwise cannibalisation ----------------------------------------------------------


def pairwise(first: PlanLine, second: PlanLine) -> float:
    return pairwise_cannibalisation(
        first, second, FakeRelations(), FakeDemand(), PRODUCTS, PredictionContext()
    )


def test_pairwise_cannibalisation_is_the_joint_effect_minus_the_single_line_effects() -> None:
    # Per North week and segment (20 baseline units each), with r = 0.8:
    # - B, promoted: A's price moves it by (r**0.5 - 1). Alone, that was charged at B's
    #   base margin on baseline units (20 x 20); jointly it hits B's promoted units at its
    #   promoted margin (30 units x (40 - 30)).
    # - A, promoted: likewise (r**0.5 - 1) x (30 x (80 - 60) - 20 x 40).
    # - E, in neither line: (r**0.3 - 1)(r**0.2 - 1) x 20 units x 20 margin, the overlap of
    #   two cuts counted twice by the single-line figures.
    per_cell = (
        (0.8**0.5 - 1) * (30 * 10 - 20 * 20)
        + (0.8**0.5 - 1) * (30 * 20 - 20 * 40)
        + (0.8**0.3 - 1) * (0.8**0.2 - 1) * 20 * 20
    )
    joint_minus_single = per_cell * 2 * 4  # two weeks, four segments

    assert pairwise(line("A"), line("B")) == pytest.approx(-joint_minus_single)
    assert pairwise(line("B"), line("A")) == pytest.approx(-joint_minus_single)


def test_pairwise_cannibalisation_counts_only_overlapping_weeks_and_segments() -> None:
    full = pairwise(line("A"), line("B"))

    assert pairwise(line("A"), line("B", start_week=61)) == pytest.approx(full / 2)
    assert pairwise(line("A", target_segment=TargetSegment.FAMILIES), line("B")) == pytest.approx(
        full / 4
    )
    assert pairwise(line("A"), line("B", start_week=62)) == 0
    assert (
        pairwise(
            line("A", target_segment=TargetSegment.FAMILIES),
            line("B", target_segment=TargetSegment.PREMIUM),
        )
        == 0
    )


def test_pairwise_cannibalisation_is_zero_across_regions_and_between_non_substitutes() -> None:
    assert pairwise(line("A"), line("B", region=Region.SOUTH)) == 0
    assert pairwise(line("A"), line("C")) == 0  # complements, not substitutes


# --- on a fitted world -----------------------------------------------------------------


def test_the_fitted_models_plug_into_the_calculators(
    small_models: tuple[DemandModel, Relations], small_history: DemandHistory
) -> None:
    model, found = small_models
    products = small_history.products
    sku_id, substitute = next(
        (sku_id, str(found.substitutes(sku_id)["sku_id"].iloc[0]))
        for sku_id in sorted(products["sku_id"])
        if not found.substitutes(sku_id).empty
    )
    promoted = line(sku_id, start_week=SMALL_AS_OF + 2)

    effects = line_effects([promoted], found, model, products)

    b = row(effects, substitute)
    assert b["relation"] == "substitute"
    assert b["units_change"] < 0 < b["cannibalised_profit"]
    assert set(effects["region"]) == {"North"}
    together = pairwise_cannibalisation(
        promoted, line(substitute, start_week=SMALL_AS_OF + 2), found, model, products
    )
    assert math.isfinite(together)
    assert together != 0
