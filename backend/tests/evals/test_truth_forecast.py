"""The true-parameter forecast and relations the best plan is optimised on (ADR 0063): the
demand model's and relations model's interfaces, answered from the ground truth.

Hand-computed on the oracle's tiny world (see test_oracle): one North store selling 100 units
per segment per week of each SKU at base price; A ₹100 (cost ₹50, elasticity -3, PCT_OFF
+0.1, BUNDLE +0.2), B ₹50 a substitute of A (theta_BA 0.5), C ₹40 a complement of A (theta_CA
-0.4); negative binomial size 10.
"""

from math import exp, sqrt

import numpy as np
import pytest

from promopilot.datagen import GeneratedDataset
from promopilot.domain import CompanyPolicy, Mechanism, PlanLine, PromoPlan, Region, TargetSegment
from promopilot.evals import Oracle
from promopilot.evals.truth_forecast import TrueForecast, TrueRelations
from promopilot.models.demand import OPTION_COLUMNS, PredictionContext
from tests.conftest import SMALL_AS_OF
from tests.evals.test_oracle import AS_OF, POLICY, a_line, tiny_products, tiny_truth

CONTEXT = PredictionContext(policy=POLICY)


def forecast(*, pull_forward: float = 0.0) -> TrueForecast:
    return TrueForecast(tiny_truth(pull_forward=pull_forward), tiny_products(), AS_OF)


def test_a_pct_off_line_is_predicted_at_its_true_expected_outcome() -> None:
    # 400 x 0.8^-3 x e^0.1 = 863.41 units at ₹80 (₹30 margin) against 400 at ₹50 margin.
    row = forecast().predict([a_line()], CONTEXT).options.iloc[0]
    cell = 863.41 / 4  # one store, four segments, one week

    assert list(row.index) == OPTION_COLUMNS
    assert row["units"] == pytest.approx(863.41, abs=0.01)
    assert row["baseline_units"] == pytest.approx(400.0)
    assert row["revenue"] == pytest.approx(69_073.18, abs=0.01)
    assert row["gross_profit"] == pytest.approx(25_902.44, abs=0.01)
    assert row["margin"] == pytest.approx(30 / 80)
    assert row["incremental_profit"] == pytest.approx(3_902.44, abs=0.01)  # net of ₹2,000
    assert row["promo_cost"] == pytest.approx(19_268.30, abs=0.01)
    assert row["anchor_discount_funding"] == pytest.approx(17_268.30, abs=0.01)
    assert row["pull_forward_units"] == pytest.approx(0.0)
    # Negative binomial noise alone: each cell's variance is mu + mu^2 / size.
    assert row["units_std"] == pytest.approx(sqrt(4 * (cell + cell**2 / 10)), abs=0.01)
    assert row["partner_units"] == 0.0


def test_the_pull_forward_dip_is_netted_off_as_the_oracle_nets_it() -> None:
    # phi 0.4 over 4 weeks: the oracle's hand-computed -₹7,439.46 for a 2-week line.
    row = forecast(pull_forward=0.4).predict([a_line(duration_weeks=2)], CONTEXT).options.iloc[0]

    assert row["units"] == pytest.approx(863.41 + 781.25, abs=0.01)
    assert row["pull_forward_units"] == pytest.approx(255.59, abs=0.01)
    assert row["incremental_units"] == pytest.approx(863.41 + 781.25 - 800 - 255.59, abs=0.02)
    assert row["incremental_profit"] == pytest.approx(-7_439.46, abs=0.01)


def test_a_segment_exclusive_line_moves_and_funds_only_its_segment() -> None:
    line = a_line(target_segment=TargetSegment.FAMILIES)
    row = forecast().predict([line], CONTEXT).options.iloc[0]

    families = 100 * 0.8**-3 * exp(0.1)  # 215.85
    assert row["units"] == pytest.approx(300 + families)
    assert row["anchor_discount_funding"] == pytest.approx(20 * families)


def test_a_bundle_partner_gets_the_lower_price_and_its_cross_effect_but_no_mechanism_effect() -> (
    None
):
    # A at ₹80 with the BUNDLE effect e^0.2; C at ₹32: 400 x 0.8^-2 x 0.8^-0.4 (A's price cut).
    line = a_line(mechanism=Mechanism.BUNDLE, bundle_partner_sku_id="C")
    row = forecast().predict([line], CONTEXT).options.iloc[0]
    partner = 400 * 0.8**-2 * 0.8**-0.4

    assert row["units"] == pytest.approx(400 * 0.8**-3 * exp(0.2), abs=0.01)
    assert row["partner_units"] == pytest.approx(partner, abs=0.01)
    assert row["partner_baseline_units"] == pytest.approx(400.0)
    assert row["partner_discount_funding"] == pytest.approx(8 * partner, abs=0.01)
    assert row["promo_cost"] == pytest.approx(
        row["anchor_discount_funding"] + row["partner_discount_funding"] + 2_000, abs=0.01
    )


def test_line_paths_break_a_prediction_down_by_week_sku_and_segment() -> None:
    paths = forecast().line_paths([a_line()], CONTEXT)

    assert list(paths.columns) == [
        "option",
        "week_id",
        "sku_id",
        "segment",
        "units",
        "baseline_units",
        "price",
    ]
    assert sorted(set(paths["week_id"])) == [11, 12, 13, 14, 15]  # the promo and 4 weeks after
    promo = paths[paths["week_id"] == 11]
    assert promo["units"].sum() == pytest.approx(863.41, abs=0.01)
    assert set(promo["price"]) == {80.0}
    assert set(paths.loc[paths["week_id"] > 11, "price"]) == {100.0}


def test_the_baseline_is_every_store_sku_segment_and_week_with_no_promotion() -> None:
    baseline = forecast().baseline([11, 13], regions=["North"], sku_ids=["B"])

    assert list(baseline.columns) == ["week_id", "store_id", "sku_id", "segment", "units"]
    assert len(baseline) == 2 * 4
    np.testing.assert_allclose(baseline["units"], 100.0)


def test_lines_the_model_cannot_predict_are_refused() -> None:
    with pytest.raises(ValueError, match="before the as-of week"):
        forecast().predict([a_line(start_week=AS_OF - 1)], CONTEXT)
    with pytest.raises(ValueError, match="unknown SKU"):
        forecast().predict([a_line(sku_id="Z")], CONTEXT)
    with pytest.raises(ValueError, match="no stores"):
        forecast().predict([a_line(region=Region.SOUTH)], CONTEXT)


def test_true_relations_report_the_true_pairs_with_the_effect_of_the_skus_price() -> None:
    relations = TrueRelations(tiny_truth())

    substitutes = relations.substitutes("A")
    assert list(substitutes["sku_id"]) == ["B"]
    assert substitutes["theta"].iloc[0] == pytest.approx(0.5)
    complements = relations.complements("A")
    assert list(complements["sku_id"]) == ["C"]
    assert complements["theta"].iloc[0] == pytest.approx(-0.4)
    # A's own units do not move with B's price in the tiny world.
    assert relations.substitutes("B")["theta"].iloc[0] == pytest.approx(0.0)
    assert relations.complements("B").empty


def test_predictions_agree_with_the_oracle_on_single_lines_of_a_generated_world(
    small_dataset: GeneratedDataset,
) -> None:
    policy = CompanyPolicy()
    true = TrueForecast(small_dataset.ground_truth, small_dataset.products, SMALL_AS_OF)
    oracle = Oracle.from_dataset(small_dataset)
    lines = [
        PlanLine(
            sku_id=sku_id,
            region=region,
            mechanism=mechanism,
            depth_pct=depth,
            duration_weeks=duration,
            start_week=SMALL_AS_OF + 2,
            target_segment=target,
            bundle_partner_sku_id=partner,
        )
        for sku_id, region, mechanism, depth, duration, target, partner in [
            ("SKU0003", Region.NORTH, Mechanism.PCT_OFF, 10, 2, TargetSegment.ALL_CUSTOMERS, None),
            ("SKU0009", Region.SOUTH, Mechanism.BOGO, 50, 1, TargetSegment.FAMILIES, None),
            (
                "SKU0013",
                Region.NORTH,
                Mechanism.FIXED_PRICE,
                15,
                1,
                TargetSegment.YOUNG_URBAN,
                None,
            ),
            (
                "SKU0003",
                Region.SOUTH,
                Mechanism.BUNDLE,
                10,
                1,
                TargetSegment.ALL_CUSTOMERS,
                "SKU0020",
            ),
        ]
    ]
    predicted = true.predict(lines, PredictionContext(policy=policy)).options

    compared = 0
    for n, line in enumerate(lines):
        [outcome] = oracle.evaluate(PromoPlan(lines=(line,)), SMALL_AS_OF, policy).lines
        if outcome.stock_capped:  # the oracle caps at stock; option generation prunes instead
            continue
        compared += 1
        row = predicted.iloc[n]
        assert row["units"] == pytest.approx(outcome.units, rel=1e-9)
        assert row["baseline_units"] == pytest.approx(outcome.baseline_units, rel=1e-9)
        assert row["revenue"] == pytest.approx(outcome.revenue, rel=1e-9)
        assert row["promo_cost"] == pytest.approx(outcome.promo_cost, rel=1e-9)
        assert row["incremental_profit"] == pytest.approx(outcome.incremental_profit, rel=1e-9)
    assert compared == len(lines)
