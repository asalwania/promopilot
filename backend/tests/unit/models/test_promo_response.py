"""The promo response model: what a promotion does to units, and how sure we are (SPEC §9.1)."""

from typing import Any

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from promopilot.datagen import GeneratedDataset, generate, load_config
from promopilot.domain import (
    CompanyPolicy,
    Mechanism,
    PlanLine,
    Region,
    Segment,
    TargetSegment,
)
from promopilot.economics import discount_funding, effective_unit_price, fixed_marketing_cost
from promopilot.models import demand
from promopilot.models.demand import DemandHistory, DemandModel, PredictionContext
from tests.conftest import SMALL_OVERRIDES, history_of

AS_OF = 52  # the first week after the small world's 52 history weeks
START = 54
CONTEXT = PredictionContext()

MEDIUM_AS_OF = 104
RECOVERY_BOUND = 0.12
"""Median |%error| of beta per SKU x segment; 7.1% measured on this fixture (ADR 0024)."""


def option(sku_id: str, /, **changes: Any) -> PlanLine:
    fields: dict[str, Any] = {
        "sku_id": sku_id,
        "region": Region.NORTH,
        "mechanism": Mechanism.PCT_OFF,
        "depth_pct": 20,
        "duration_weeks": 2,
        "start_week": START,
        "target_segment": TargetSegment.ALL_CUSTOMERS,
    }
    return PlanLine(**(fields | changes))


@pytest.fixture(scope="module")
def model(small_history: DemandHistory) -> DemandModel:
    return demand.fit(small_history, as_of_week=AS_OF, seed=7)


@pytest.fixture(scope="module")
def skus(small_history: DemandHistory) -> list[str]:
    return list(small_history.products["sku_id"])


@pytest.fixture(scope="module")
def base_prices(small_history: DemandHistory) -> dict[str, float]:
    products = small_history.products
    return dict(zip(products["sku_id"], products["base_price"], strict=True))


@pytest.fixture(scope="module")
def unit_costs(small_history: DemandHistory) -> dict[str, float]:
    products = small_history.products
    return dict(zip(products["sku_id"], products["unit_cost"], strict=True))


def test_deeper_discounts_raise_predicted_units(model: DemandModel, skus: list[str]) -> None:
    shallow = [option(sku, depth_pct=10) for sku in skus]
    deep = [option(sku, depth_pct=30) for sku in skus]

    units = model.predict(shallow + deep, CONTEXT).options["units"].to_numpy()

    assert (units[len(skus) :] > units[: len(skus)]).all()


def test_a_competitor_undercut_lowers_predicted_units(
    model: DemandModel, skus: list[str], base_prices: dict[str, float]
) -> None:
    options = [option(sku) for sku in skus]
    undercut = PredictionContext(
        competitor_prices={(Region.NORTH, sku): 0.7 * base_prices[sku] for sku in skus}
    )

    usual = model.predict(options, CONTEXT).options["units"]
    undercut_units = model.predict(options, undercut).options["units"]

    assert (undercut_units < usual).all()


def test_a_segment_exclusive_offer_changes_only_that_segment(
    model: DemandModel, skus: list[str]
) -> None:
    options = [option(sku, target_segment=TargetSegment.PREMIUM) for sku in skus]

    segments = model.predict(options, CONTEXT).segments

    premium = segments[segments["segment"] == Segment.PREMIUM.value]
    others = segments[segments["segment"] != Segment.PREMIUM.value]
    assert len(premium) == len(skus)
    assert (premium["units"] > premium["baseline_units"]).all()
    np.testing.assert_allclose(others["units"], others["baseline_units"])


def test_predictions_have_a_positive_std_and_are_deterministic_for_a_seed(
    small_history: DemandHistory, model: DemandModel, skus: list[str]
) -> None:
    options = [option(sku) for sku in skus]

    first = model.predict(options, CONTEXT)
    again = demand.fit(small_history, as_of_week=AS_OF, seed=7).predict(options, CONTEXT)

    assert_frame_equal(again.options, first.options)
    assert_frame_equal(again.segments, first.segments)
    assert (first.options["units_std"] > 0).all()
    assert (first.segments["units_std"] > 0).all()


def test_uplift_is_net_of_the_pull_forward_dip(model: DemandModel, skus: list[str]) -> None:
    short = [option(sku, duration_weeks=1) for sku in skus]
    long = [option(sku, duration_weeks=4) for sku in skus]

    predicted = model.predict(short + long, CONTEXT).options

    assert (predicted["pull_forward_units"] > 0).all()
    np.testing.assert_allclose(
        predicted["incremental_units"],
        predicted["units"] - predicted["baseline_units"] - predicted["pull_forward_units"],
    )
    # Longer promotions pull more demand forward (ADR 0016).
    dips = predicted["pull_forward_units"].to_numpy()
    assert (dips[len(skus) :] > dips[: len(skus)]).all()


def test_promo_economics_follow_the_shared_definitions(
    model: DemandModel,
    skus: list[str],
    base_prices: dict[str, float],
    unit_costs: dict[str, float],
) -> None:
    sku = skus[0]
    policy = CompanyPolicy()
    line = option(sku, depth_pct=20, target_segment=TargetSegment.FAMILIES)

    predicted = model.predict([line], PredictionContext(policy=policy))

    outcome = predicted.options.iloc[0]
    segments = predicted.segments
    families = float(segments.loc[segments["segment"] == Segment.FAMILIES.value, "units"].sum())
    base, cost = base_prices[sku], unit_costs[sku]
    price = effective_unit_price(Mechanism.PCT_OFF, base, 20)
    others = outcome["units"] - families  # other segments still pay the base price (ADR 0006)
    assert outcome["revenue"] == pytest.approx(families * price + others * base)
    assert outcome["gross_profit"] == pytest.approx(
        families * (price - cost) + others * (base - cost)
    )
    assert outcome["margin"] == pytest.approx(outcome["gross_profit"] / outcome["revenue"])
    assert outcome["promo_cost"] == pytest.approx(
        discount_funding(base, price, {Segment.FAMILIES: families}, line.target_segment)
        + fixed_marketing_cost(Mechanism.PCT_OFF, 2, policy)
    )


def test_prediction_is_vectorised_over_a_batch_of_options(
    small_dataset: GeneratedDataset, model: DemandModel, skus: list[str]
) -> None:
    anchor, partner = small_dataset.ground_truth.complement_pairs[0]
    options = [
        option(skus[0]),
        option(skus[1], mechanism=Mechanism.BOGO, depth_pct=50, region=Region.SOUTH),
        option(anchor, mechanism=Mechanism.BUNDLE, depth_pct=15, bundle_partner_sku_id=partner),
        option(skus[2], target_segment=TargetSegment.YOUNG_URBAN, duration_weeks=4),
    ]

    batch = model.predict(options, CONTEXT)
    alone = [model.predict([line], CONTEXT) for line in options]

    assert_frame_equal(batch.options, pd.concat([one.options for one in alone], ignore_index=True))
    segments = pd.concat(
        [one.segments.assign(option=n) for n, one in enumerate(alone)], ignore_index=True
    )
    assert_frame_equal(batch.segments, segments)


def test_options_before_the_as_of_week_are_rejected(model: DemandModel, skus: list[str]) -> None:
    with pytest.raises(ValueError, match="before the as-of week"):
        model.predict([option(skus[0], start_week=AS_OF - 1)], CONTEXT)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"sku_id": "SKU9999"}, "unknown SKU SKU9999"),
        (
            {"mechanism": Mechanism.BUNDLE, "bundle_partner_sku_id": "SKU9999"},
            "unknown SKU SKU9999",
        ),
        ({"region": Region.EAST}, "no stores in East"),
    ],
)
def test_options_the_model_has_no_history_for_are_rejected(
    model: DemandModel, skus: list[str], changes: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        model.predict([option(skus[0], **changes)], CONTEXT)


@pytest.fixture(scope="module")
def medium_model(medium_dataset: GeneratedDataset) -> DemandModel:
    return demand.fit(history_of(medium_dataset), as_of_week=MEDIUM_AS_OF, seed=3)


@pytest.mark.model
def test_recovered_elasticities_are_close_to_the_true_ones(
    medium_dataset: GeneratedDataset, medium_model: DemandModel
) -> None:
    coefficients = medium_model.coefficients()
    beta = coefficients[coefficients["parameter"] == "beta"].set_index(["sku_id", "level"])
    truth = {
        (sku.sku_id, segment.value): value
        for sku in medium_dataset.ground_truth.skus
        for segment, value in sku.elasticity.items()
    }

    true = np.array([truth[key] for key in beta.index])
    error = np.abs(beta["estimate"].to_numpy() - true) / np.abs(true)
    assert len(error) == len(truth)
    assert np.median(error) < RECOVERY_BOUND
    assert (beta["std_error"] > 0).all()


def fitted_bogo_effect(bogo_effect: list[float]) -> float:
    overrides = SMALL_OVERRIDES | {"demand": {"mechanism_effect": {"BOGO": bogo_effect}}}
    world = generate(load_config(overrides=overrides), seed=11)
    coefficients = demand.fit(history_of(world), as_of_week=AS_OF, seed=7).coefficients()
    bogo = (coefficients["parameter"] == "mu") & (coefficients["level"] == Mechanism.BOGO.value)
    return float(coefficients.loc[bogo, "estimate"].mean())


@pytest.mark.model
def test_mechanism_effects_are_estimated_from_promo_history() -> None:
    weak = fitted_bogo_effect([0.0, 0.05])
    strong = fitted_bogo_effect([0.45, 0.60])

    assert strong > weak + 0.2


def test_the_registry_metrics_report_the_response_fit(model: DemandModel, skus: list[str]) -> None:
    metrics = model.metrics

    assert 0 < metrics["response_skus_fitted"] <= len(skus)
    assert metrics["elasticity_median_std_error"] > 0
