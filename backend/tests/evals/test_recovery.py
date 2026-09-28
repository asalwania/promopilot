"""Model-recovery metrics: how close the fitted models come to the ground truth (SPEC §12.2,
ADR 0064), on hand-computed cases and on the small generated world."""

import pytest

from promopilot.datagen import GeneratedDataset
from promopilot.evals import EvalWorld, FittedModels
from promopilot.evals.recovery import (
    baseline_wape,
    detection,
    elasticity_recovery,
    median_abs_pct_error,
    precision_recall,
    recovery_metrics,
)
from promopilot.models.demand import DemandModel
from promopilot.models.relations import Relations
from tests.conftest import SMALL_AS_OF

# --- median absolute % error -----------------------------------------------------------


def test_the_median_absolute_percent_error_is_relative_to_the_truth() -> None:
    # Errors: |-2.2 - -2.0| / 2 = 0.1, |-0.6 - -1.0| / 1 = 0.4, |-3.0 - -3.0| / 3 = 0.
    errors = median_abs_pct_error(estimated=[-2.2, -0.6, -3.0], true=[-2.0, -1.0, -3.0])

    assert errors == pytest.approx(0.1)


def test_the_median_of_an_even_count_is_the_mean_of_the_middle_two() -> None:
    # Errors 0.5, 0.1, 0.2, 0.0 -> middle two 0.1 and 0.2.
    errors = median_abs_pct_error(estimated=[-1.5, -1.1, -2.4, -2.0], true=[-1.0] * 2 + [-2.0] * 2)

    assert errors == pytest.approx(0.15)


def test_a_zero_true_elasticity_has_no_percent_error() -> None:
    with pytest.raises(ValueError, match="zero"):
        median_abs_pct_error(estimated=[-1.0], true=[0.0])


def test_elasticity_recovery_counts_the_estimates_within_the_target() -> None:
    true = {("A", "Families"): -2.0, ("A", "Premium"): -1.0, ("B", "Families"): -3.0}
    estimated = {("A", "Families"): -2.2, ("A", "Premium"): -0.6, ("B", "Families"): -3.0}

    metric = elasticity_recovery(estimated, true)

    assert metric.name == "elasticity_recovery"
    assert metric.value == pytest.approx(0.1)
    assert (metric.count, metric.of) == (2, 3), "0.1 and 0 are within 20%; 0.4 is not"
    assert (metric.target, metric.direction, metric.passed) == (0.2, "at_most", True)


def test_elasticity_recovery_fails_above_the_target() -> None:
    metric = elasticity_recovery({("A", "Families"): -1.5}, {("A", "Families"): -1.0})

    assert metric.value == pytest.approx(0.5)
    assert (metric.count, metric.of, metric.passed) == (0, 1, False)


def test_a_true_elasticity_the_model_did_not_estimate_is_an_error() -> None:
    with pytest.raises(ValueError, match="A"):
        elasticity_recovery({}, {("A", "Families"): -1.0})


# --- precision and recall --------------------------------------------------------------


def test_precision_is_over_the_found_pairs_and_recall_over_the_true_ones() -> None:
    found = {("A", "B"), ("A", "C"), ("C", "D")}
    true = {("A", "B"), ("C", "D"), ("D", "E"), ("E", "F")}

    assert precision_recall(found, true) == (2 / 3, 2 / 4)


def test_precision_or_recall_with_nothing_to_divide_by_is_undefined() -> None:
    assert precision_recall(set(), {("A", "B")}) == (None, 0.0)
    assert precision_recall({("A", "B")}, set()) == (0.0, None)


def test_pairs_are_unordered() -> None:
    assert precision_recall({("B", "A")}, {("A", "B")}) == (1.0, 1.0)


def test_detection_reports_precision_and_recall_against_their_targets() -> None:
    found = {("A", "B"), ("A", "C"), ("C", "D"), ("D", "E"), ("E", "F")}
    true = {("A", "B"), ("C", "D"), ("D", "E"), ("E", "F"), ("F", "G")}

    precision, recall = detection("substitute", found, true)

    assert (precision.name, precision.value, precision.count, precision.of) == (
        "substitute_precision",
        0.8,
        4,
        5,
    )
    assert (precision.target, precision.direction, precision.passed) == (0.8, "at_least", True)
    assert (recall.name, recall.value, recall.count, recall.of) == (
        "substitute_recall",
        0.8,
        4,
        5,
    )
    assert (recall.target, recall.direction, recall.passed) == (0.7, "at_least", True)


def test_detection_with_nothing_found_has_no_precision_and_fails_recall() -> None:
    precision, recall = detection("complement", set(), {("A", "B")})

    assert (precision.name, precision.value, precision.of, precision.passed) == (
        "complement_precision",
        None,
        0,
        None,
    )
    assert (recall.value, recall.count, recall.of, recall.passed) == (0.0, 0, 1, False)


# --- baseline WAPE ---------------------------------------------------------------------


def test_baseline_wape_is_reported_at_three_grains_with_an_aim() -> None:
    metrics = baseline_wape(
        {"baseline_wape": 0.44, "baseline_wape_store_sku": 0.25, "baseline_wape_region_sku": 0.14}
    )

    assert [(m.name, m.value) for m in metrics] == [
        ("baseline_wape", 0.44),
        ("baseline_wape_store_sku", 0.25),
        ("baseline_wape_region_sku", 0.14),
    ]
    for metric in metrics:
        assert (metric.target, metric.passed) == (None, None), "reported, never judged"
        assert (metric.aim, metric.direction) == (0.25, "at_most")
        assert (metric.count, metric.of) == (0, 0)


# --- on a fitted world -----------------------------------------------------------------


async def test_recovery_reads_the_worlds_models_at_its_default_week(
    small_dataset: GeneratedDataset, small_models: tuple[DemandModel, Relations]
) -> None:
    world = EvalWorld(small_dataset, fitted={SMALL_AS_OF: FittedModels(*small_models)})
    assert world.default_as_of_week == SMALL_AS_OF

    metrics = {metric.name: metric for metric in await recovery_metrics(world)}

    assert list(metrics) == [
        "elasticity_recovery",
        "substitute_precision",
        "substitute_recall",
        "complement_precision",
        "complement_recall",
        "baseline_wape",
        "baseline_wape_store_sku",
        "baseline_wape_region_sku",
    ]
    truth = small_dataset.ground_truth
    elasticity = metrics["elasticity_recovery"]
    assert elasticity.of == len(truth.skus) * 4, "every SKU x segment"
    assert elasticity.value is not None
    assert 0 < elasticity.value < 1
    assert metrics["substitute_recall"].of == len(truth.substitute_pairs)
    assert metrics["complement_recall"].of == len(truth.complement_pairs)
    demand_model, _ = small_models
    assert metrics["baseline_wape"].value == demand_model.metrics["baseline_wape"]
