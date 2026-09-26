import numpy as np
import pytest

from promopilot.datagen import GeneratedDataset
from promopilot.datagen.truth import MECHANISMS, GroundTruth, TrueDemand
from promopilot.domain import Mechanism, Region, Segment

SEGMENTS = list(Segment)


def test_ground_truth_holds_every_true_parameter(small_dataset: GeneratedDataset) -> None:
    truth = small_dataset.ground_truth
    sku = truth.skus[0]

    assert len(truth.skus) == len(small_dataset.products)
    assert set(sku.elasticity) == set(Segment)
    assert all(-3.5 <= beta <= -0.5 for s in truth.skus for beta in s.elasticity.values())
    assert sku.competitor_sensitivity > 0
    assert set(sku.mechanism_effect) == set(Mechanism)
    assert sku.pull_forward > 0
    assert truth.pull_forward_window_weeks == 4
    assert sku.dispersion > 0
    assert sku.base_level != 0
    assert sku.season_amplitude >= 0
    assert set(truth.holiday_sensitivity) == set(small_dataset.products["category"])
    assert truth.substitute_pairs
    assert truth.complement_pairs
    assert {(e.sku_id, e.other_sku_id) for e in truth.cross_effects if e.theta > 0} >= {
        pair for pair in truth.substitute_pairs
    }


def test_substitutes_share_a_subcategory_and_complements_cross_categories(
    small_dataset: GeneratedDataset,
) -> None:
    truth = small_dataset.ground_truth
    products = small_dataset.products.set_index("sku_id")

    for a, b in truth.substitute_pairs:
        assert products.loc[a, "subcategory"] == products.loc[b, "subcategory"]
    for a, b in truth.complement_pairs:
        assert products.loc[a, "category"] != products.loc[b, "category"]
    assert len(truth.complement_pairs) == small_dataset.config.complement_pairs


def test_default_world_has_about_15_percent_substitute_pairs_and_40_complements(
    default_dataset: GeneratedDataset,
) -> None:
    truth = default_dataset.ground_truth
    products = default_dataset.products
    within_pairs = sum(n * (n - 1) // 2 for n in products.groupby("subcategory").size())

    assert 0.10 <= len(truth.substitute_pairs) / within_pairs <= 0.20
    assert len(truth.complement_pairs) == 40


def test_ground_truth_round_trips_through_json(small_dataset: GeneratedDataset) -> None:
    truth = small_dataset.ground_truth

    assert GroundTruth.model_validate_json(truth.model_dump_json()) == truth


def scenario(
    demand: TrueDemand, weeks: int
) -> tuple[np.ndarray, np.ndarray]:  # prices (W, G, N), mechanisms (W, G, N)
    prices = np.tile(demand.reference_prices, (weeks, len(SEGMENTS), 1))
    mechanisms = np.full(prices.shape, -1)
    return prices, mechanisms


def test_a_segment_exclusive_price_cut_moves_only_the_targeted_segment(
    small_dataset: GeneratedDataset,
) -> None:
    demand = TrueDemand(small_dataset.ground_truth)
    prices, mechanisms = scenario(demand, weeks=2)
    baseline = demand.expected_units(Region.NORTH, 60, prices, mechanisms)

    families = SEGMENTS.index(Segment.FAMILIES)
    prices[:, families, 0] *= 0.8
    mechanisms[:, families, 0] = MECHANISMS.index(Mechanism.PCT_OFF)
    promoted = demand.expected_units(Region.NORTH, 60, prices, mechanisms)

    others = [g for g in range(len(SEGMENTS)) if g != families]
    assert (promoted[:, :, families, 0] > 1.2 * baseline[:, :, families, 0]).all()
    np.testing.assert_allclose(promoted[:, :, others, :], baseline[:, :, others, :])


def test_a_price_cut_on_a_substitute_takes_units_and_on_a_complement_adds_units(
    small_dataset: GeneratedDataset,
) -> None:
    truth = small_dataset.ground_truth
    demand = TrueDemand(truth)
    index = {sku.sku_id: i for i, sku in enumerate(truth.skus)}
    (sub_a, sub_b), (comp_a, comp_b) = truth.substitute_pairs[0], truth.complement_pairs[0]
    prices, mechanisms = scenario(demand, weeks=1)
    baseline = demand.expected_units(Region.SOUTH, 60, prices, mechanisms)

    prices[:, :, index[sub_b]] *= 0.7
    prices[:, :, index[comp_b]] *= 0.7
    promoted = demand.expected_units(Region.SOUTH, 60, prices, mechanisms)

    assert (promoted[..., index[sub_a]] < baseline[..., index[sub_a]]).all()
    assert (promoted[..., index[comp_a]] > baseline[..., index[comp_a]]).all()


def test_a_promotion_dips_demand_in_the_weeks_after_it(small_dataset: GeneratedDataset) -> None:
    demand = TrueDemand(small_dataset.ground_truth)
    prices, mechanisms = scenario(demand, weeks=6)
    baseline = demand.expected_units(Region.NORTH, 50, prices, mechanisms)

    prices[:2, :, 0] *= 0.8
    promoted = demand.expected_units(Region.NORTH, 50, prices, mechanisms)

    after = slice(2, 6)
    assert (promoted[:, after, :, 0] < baseline[:, after, :, 0]).all()
    np.testing.assert_allclose(promoted[:, after, :, 1:], baseline[:, after, :, 1:])


def test_expected_units_are_positive_for_every_store_in_the_region(
    small_dataset: GeneratedDataset,
) -> None:
    demand = TrueDemand(small_dataset.ground_truth)
    prices, mechanisms = scenario(demand, weeks=3)

    units = demand.expected_units(Region.SOUTH, 0, prices, mechanisms)

    assert units.shape == (
        small_dataset.config.stores_per_region,
        3,
        len(SEGMENTS),
        len(small_dataset.products),
    )
    assert (units > 0).all()
    assert demand.store_ids(Region.SOUTH) == list(
        small_dataset.stores.loc[small_dataset.stores["region"] == "South", "store_id"]
    )


def test_expected_units_rejects_weeks_outside_the_generated_timeline(
    small_dataset: GeneratedDataset,
) -> None:
    demand = TrueDemand(small_dataset.ground_truth)
    prices, mechanisms = scenario(demand, weeks=2)

    with pytest.raises(ValueError, match="timeline"):
        demand.expected_units(
            Region.NORTH, small_dataset.config.total_weeks - 1, prices, mechanisms
        )
