from itertools import combinations

import numpy as np
import pandas as pd

from promopilot.datagen import GeneratedDataset
from promopilot.datagen.truth import TrueDemand
from promopilot.domain import CompanyPolicy, Region


def pair_lift(baskets: pd.DataFrame, pairs: list[tuple[str, str]]) -> list[float]:
    n = len(baskets)
    item_counts: dict[str, int] = {}
    pair_counts: dict[frozenset[str], int] = {}
    wanted = {frozenset(pair) for pair in pairs}
    for items in baskets["sku_ids"]:
        for sku in items:
            item_counts[sku] = item_counts.get(sku, 0) + 1
        for a, b in combinations(items, 2):
            key = frozenset((a, b))
            if key in wanted:
                pair_counts[key] = pair_counts.get(key, 0) + 1
    return [
        (pair_counts.get(frozenset((a, b)), 0) / n)
        / ((item_counts.get(a, 0) / n) * (item_counts.get(b, 0) / n) or np.inf)
        for a, b in pairs
    ]


def test_baskets_are_sampled_at_the_configured_count(default_dataset: GeneratedDataset) -> None:
    baskets = default_dataset.baskets

    assert len(baskets) == 200_000
    assert baskets["basket_id"].is_unique
    assert baskets["sku_ids"].map(len).min() >= 1
    assert baskets["week_id"].max() < default_dataset.config.history_weeks


def test_true_complement_pairs_show_basket_lift_above_one(
    default_dataset: GeneratedDataset,
) -> None:
    lifts = pair_lift(default_dataset.baskets, default_dataset.ground_truth.complement_pairs)

    assert min(lifts) > 1
    assert np.median(lifts) > 1.5


def test_baskets_reference_real_stores_skus_and_segments(small_dataset: GeneratedDataset) -> None:
    baskets = small_dataset.baskets
    skus = set(small_dataset.products["sku_id"])

    assert set(baskets["store_id"]) <= set(small_dataset.stores["store_id"])
    assert set(baskets["segment"]) <= {"Value Seekers", "Families", "Premium", "Young Urban"}
    assert all(set(items) <= skus for items in baskets["sku_ids"])
    assert all(list(items) == sorted(set(items)) for items in baskets["sku_ids"])


def latest_snapshot(dataset: GeneratedDataset) -> pd.DataFrame:
    inventory = dataset.inventory
    return inventory[inventory["snapshot_week"] == dataset.config.history_weeks - 1]


def test_inventory_has_a_weekly_snapshot_per_store_and_sku(small_dataset: GeneratedDataset) -> None:
    inventory = small_dataset.inventory
    expected = (
        small_dataset.config.history_weeks * len(small_dataset.stores) * len(small_dataset.products)
    )

    assert len(inventory) == expected
    assert not inventory.duplicated(["snapshot_week", "store_id", "sku_id"]).any()


def test_no_stock_value_is_negative(small_dataset: GeneratedDataset) -> None:
    inventory = small_dataset.inventory

    for column in ["on_hand", "on_order", "safety_stock", "days_of_cover"]:
        assert (inventory[column] >= 0).all(), column


def test_the_overstock_flag_follows_the_company_policy_threshold(
    small_dataset: GeneratedDataset,
) -> None:
    inventory = small_dataset.inventory
    threshold_days = CompanyPolicy().overstock_threshold_weeks * 7

    assert inventory["is_overstock"].equals(inventory["days_of_cover"] > threshold_days)


def test_10_to_15_percent_of_skus_are_overstocked_and_about_5_percent_low(
    default_dataset: GeneratedDataset,
) -> None:
    by_sku = latest_snapshot(default_dataset).groupby("sku_id")
    overstocked = by_sku["is_overstock"].all()
    low = by_sku["days_of_cover"].median() < 7

    assert 0.10 <= overstocked.mean() <= 0.15
    assert 0.03 <= low.mean() <= 0.07


def test_the_demo_brief_s_400g_namkeen_packs_are_overstocked(
    default_dataset: GeneratedDataset,
) -> None:
    snapshot = latest_snapshot(default_dataset).merge(default_dataset.products[["sku_id", "name"]])
    namkeen_400g = snapshot[snapshot["name"].str.contains("Namkeen 400g")]

    assert len(namkeen_400g) > 0
    assert namkeen_400g["is_overstock"].all()


def test_the_future_horizon_covers_52_weeks_by_default(default_dataset: GeneratedDataset) -> None:
    truth = default_dataset.ground_truth
    calendar = default_dataset.calendar
    demand = TrueDemand(truth)
    horizon = slice(104, 156)

    assert truth.horizon_weeks == 52
    assert calendar["week_id"].max() == 155
    assert all(len(prices) == 156 for prices in truth.competitor_prices[Region.WEST].values())
    prices = np.tile(demand.reference_prices, (horizon.stop - horizon.start, 4, 1))
    units = demand.expected_units(Region.WEST, 104, prices, np.full(prices.shape, -1))
    assert (units > 0).all()


def test_the_horizon_length_is_configurable(small_dataset: GeneratedDataset) -> None:
    assert small_dataset.ground_truth.horizon_weeks == 12
    assert small_dataset.calendar["week_id"].max() == 52 + 12 - 1
