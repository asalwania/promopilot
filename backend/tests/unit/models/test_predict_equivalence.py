"""The demand model's prediction numbers are the pre-#113 pipeline's, bit for bit (ADR 0087).

`reference_demand` is a frozen copy of the pipeline before it was rebuilt on distinct keys.
Every column of `predict`, `line_paths` and `response_rows` must equal it exactly, so no
option, plan, simulation or recorded session changes.
"""

import re
from typing import Any

import numpy as np
import pytest
from pandas.testing import assert_frame_equal, assert_series_equal

from promopilot.datagen import GeneratedDataset
from promopilot.domain import Mechanism, PlanLine, Region, TargetSegment
from promopilot.models.demand import DemandModel, PredictionContext
from promopilot.models.relations import Relations
from tests.conftest import SMALL_AS_OF
from tests.unit.models.reference_demand import Reference

LAST_WEEK = 63
"""The small world's last calendar week: 52 history weeks and 12 horizon weeks."""


def line(sku_id: str, /, **changes: Any) -> PlanLine:
    fields: dict[str, Any] = {
        "sku_id": sku_id,
        "region": Region.NORTH,
        "mechanism": Mechanism.PCT_OFF,
        "depth_pct": 20,
        "duration_weeks": 2,
        "start_week": SMALL_AS_OF + 2,
        "target_segment": TargetSegment.ALL_CUSTOMERS,
    }
    return PlanLine(**(fields | changes))


@pytest.fixture(scope="module")
def model(small_models: tuple[DemandModel, Relations]) -> DemandModel:
    return small_models[0]


@pytest.fixture(scope="module")
def batch(small_dataset: GeneratedDataset) -> list[PlanLine]:
    """Every mechanism and target segment, durations 1-4, a start at the as-of week and a
    pull-forward cut short by the calendar's end, a BUNDLE, and a line repeated."""
    skus = list(small_dataset.products["sku_id"])
    anchor, partner = small_dataset.ground_truth.complement_pairs[0]
    lines = [
        line(skus[0]),
        line(skus[0], target_segment=TargetSegment.FAMILIES, depth_pct=35),
        line(skus[1], mechanism=Mechanism.BOGO, depth_pct=50, region=Region.SOUTH),
        line(skus[2], mechanism=Mechanism.FIXED_PRICE, depth_pct=15, duration_weeks=4),
        line(skus[3], start_week=SMALL_AS_OF, duration_weeks=1),
        line(skus[4], start_week=LAST_WEEK - 1, target_segment=TargetSegment.PREMIUM),
        line(skus[5], start_week=LAST_WEEK, duration_weeks=1, region=Region.SOUTH),
        line(anchor, mechanism=Mechanism.BUNDLE, depth_pct=15, bundle_partner_sku_id=partner),
        line(
            anchor,
            mechanism=Mechanism.BUNDLE,
            depth_pct=25,
            bundle_partner_sku_id=partner,
            region=Region.SOUTH,
            target_segment=TargetSegment.YOUNG_URBAN,
            duration_weeks=3,
        ),
    ]
    lines += [
        line(skus[6], target_segment=target, duration_weeks=duration)
        for target in TargetSegment
        for duration in (1, 3)
    ]
    return [*lines, lines[0], lines[7]]


CONTEXTS = {
    "default": PredictionContext(),
    "competitor prices": PredictionContext(
        competitor_prices={(Region.NORTH, "SKU0001"): 1.0, (Region.SOUTH, "SKU0002"): 500.0}
    ),
}


def assert_predictions_equal(model: DemandModel, lines: list[PlanLine], context: Any) -> None:
    reference = Reference(model).predict(lines, context)
    predicted = model.predict(lines, context)
    assert_frame_equal(predicted.options, reference.options, check_exact=True)
    assert_frame_equal(predicted.segments, reference.segments, check_exact=True)


@pytest.mark.parametrize("context", CONTEXTS.values(), ids=CONTEXTS.keys())
def test_predict_equals_the_reference_bit_for_bit(
    model: DemandModel, batch: list[PlanLine], context: PredictionContext
) -> None:
    assert_predictions_equal(model, batch, context)


def test_predict_equals_the_reference_for_one_line_and_a_shuffled_batch(
    model: DemandModel, batch: list[PlanLine]
) -> None:
    assert_predictions_equal(model, batch[:1], PredictionContext())
    shuffled = [batch[n] for n in np.random.default_rng(3).permutation(len(batch))]
    assert_predictions_equal(model, shuffled, PredictionContext())


@pytest.mark.parametrize("context", CONTEXTS.values(), ids=CONTEXTS.keys())
def test_line_paths_equal_the_reference_bit_for_bit(
    model: DemandModel, batch: list[PlanLine], context: PredictionContext
) -> None:
    assert_frame_equal(
        model.line_paths(batch, context),
        Reference(model).line_paths(batch, context),
        check_exact=True,
    )


@pytest.mark.parametrize("context", CONTEXTS.values(), ids=CONTEXTS.keys())
def test_response_rows_equal_the_reference_bit_for_bit(
    model: DemandModel, batch: list[PlanLine], context: PredictionContext
) -> None:
    rows = model.response_rows(batch, context)
    reference = Reference(model).response_rows(batch, context)
    assert_frame_equal(rows.rows, reference.rows, check_exact=True)
    assert_frame_equal(rows.design, reference.design, check_exact=True)
    assert_frame_equal(rows.estimate, reference.estimate, check_exact=True)
    assert_frame_equal(rows.std_error, reference.std_error, check_exact=True)
    assert_series_equal(rows.dispersion, reference.dispersion, check_exact=True)


INVALID = {
    "unknown SKU": {"sku_id": "SKU9999"},
    "unknown partner": {
        "mechanism": Mechanism.BUNDLE,
        "depth_pct": 15,
        "bundle_partner_sku_id": "SKU9999",
    },
    "region without stores": {"region": Region.EAST},
    "before the as-of week": {"start_week": SMALL_AS_OF - 1},
    "past the calendar": {"start_week": LAST_WEEK, "duration_weeks": 2},
}


@pytest.mark.parametrize("changes", INVALID.values(), ids=INVALID.keys())
def test_an_option_the_model_cannot_predict_raises_what_the_reference_raises(
    model: DemandModel, batch: list[PlanLine], changes: dict[str, Any]
) -> None:
    lines = [*batch[:2], line(batch[0].sku_id, **changes)]
    with pytest.raises(ValueError, match=r".") as expected:
        Reference(model).predict(lines, PredictionContext())
    for call in (model.predict, model.line_paths, model.response_rows):
        with pytest.raises(ValueError, match=f"^{re.escape(str(expected.value))}$"):
            call(lines, PredictionContext())
