import json

import numpy as np
import pandas as pd
import pytest

from promopilot.datagen import GeneratedDataset, GeneratorConfig, generate
from promopilot.domain import Segment, TargetSegment

TABLES = [
    "products",
    "stores",
    "calendar",
    "competitor_prices",
    "promotions_history",
    "sales_weekly",
]


def test_same_seed_and_config_give_identical_tables_and_ground_truth(
    small_config: GeneratorConfig, small_dataset: GeneratedDataset
) -> None:
    again = generate(small_config, seed=small_dataset.seed)

    for table in TABLES:
        pd.testing.assert_frame_equal(getattr(again, table), getattr(small_dataset, table))
    assert again.ground_truth.model_dump_json() == small_dataset.ground_truth.model_dump_json()


def test_a_different_seed_gives_a_different_world(
    small_config: GeneratorConfig, small_dataset: GeneratedDataset
) -> None:
    other = generate(small_config, seed=small_dataset.seed + 1)

    assert not other.sales_weekly["units"].equals(small_dataset.sales_weekly["units"])


def test_sales_cover_every_store_sku_and_history_week(small_dataset: GeneratedDataset) -> None:
    config = small_dataset.config
    sales = small_dataset.sales_weekly

    expected_rows = len(small_dataset.stores) * len(small_dataset.products) * config.history_weeks
    assert len(sales) == expected_rows
    assert sales["week_id"].max() == config.history_weeks - 1


def test_segment_units_add_up_to_units(small_dataset: GeneratedDataset) -> None:
    for row in small_dataset.sales_weekly.head(500).itertuples():
        by_segment = json.loads(str(row.segment_units))
        assert set(by_segment) == {segment.value for segment in Segment}
        assert sum(by_segment.values()) == row.units


def test_about_15_percent_of_sku_region_weeks_are_on_promotion(
    default_dataset: GeneratedDataset,
) -> None:
    promos = default_dataset.promotions_history
    config = default_dataset.config
    # A bundle promotes its partner too.
    partner_weeks = promos.loc[promos["bundle_sku_id"].notna(), "duration"].sum()
    promo_weeks = promos["duration"].sum() + partner_weeks
    total = len(default_dataset.products) * len(config.regions) * config.history_weeks

    assert 0.12 <= promo_weeks / total <= 0.18


def test_promo_weeks_outsell_non_promo_weeks_for_more_than_90_percent_of_skus(
    default_dataset: GeneratedDataset,
) -> None:
    sales = default_dataset.sales_weekly
    mean_units = sales.groupby(["sku_id", "on_promo"])["units"].mean().unstack()

    assert (mean_units[True] > mean_units[False]).mean() > 0.90


def test_segment_exclusive_promotions_move_only_the_targeted_segment(
    default_dataset: GeneratedDataset,
) -> None:
    sales = default_dataset.sales_weekly.merge(default_dataset.stores[["store_id", "region"]])
    promos = default_dataset.promotions_history
    exclusive = promos[
        (promos["target_segment"] != TargetSegment.ALL_CUSTOMERS.value)
        & promos["bundle_sku_id"].isna()
    ].head(150)
    by_sku_region = dict(tuple(sales.groupby(["sku_id", "region"])))
    target_ratios, other_ratios = [], []
    columns = ["sku_id", "region", "start_week", "duration", "target_segment"]
    for sku_id, region, start, duration, target in exclusive[columns].itertuples(
        index=False, name=None
    ):
        rows = by_sku_region[(sku_id, region)]
        in_promo = rows["week_id"].between(start, start + duration - 1)
        quiet = ~rows["on_promo"]
        segments = pd.DataFrame(rows["segment_units"].map(json.loads).tolist(), index=rows.index)
        during, normal = segments[in_promo].mean(), segments[quiet].mean()
        others = [s.value for s in Segment if s.value != target]
        target_ratios.append(during[target] / max(normal[target], 0.1))
        other_ratios.append(during[others].sum() / max(normal[others].sum(), 0.1))

    assert np.median(target_ratios) > 1.3
    assert 0.85 <= np.median(other_ratios) <= 1.15


def test_historical_bundles_pair_only_true_complements(default_dataset: GeneratedDataset) -> None:
    promos = default_dataset.promotions_history
    bundles = promos[promos["mechanism"] == "BUNDLE"]
    complements = {frozenset(pair) for pair in default_dataset.ground_truth.complement_pairs}

    assert len(bundles) > 0
    assert bundles["bundle_sku_id"].notna().all()
    assert all(
        frozenset((row.sku_id, row.bundle_sku_id)) in complements for row in bundles.itertuples()
    )
    assert promos.loc[promos["mechanism"] != "BUNDLE", "bundle_sku_id"].isna().all()


def test_a_simple_log_log_regression_roughly_recovers_own_price_elasticity(
    default_dataset: GeneratedDataset,
) -> None:
    """SPEC §8.4 sanity check: not the real model, just evidence the signal is there.

    Our price appears twice in the true demand function (own price and the competitor
    price index), so the regression controls for the index as the real model must.
    """
    sales = default_dataset.sales_weekly.merge(default_dataset.stores[["store_id", "region"]])
    open_price = sales["target_segment"].isna() | sales["target_segment"].eq("All customers")
    regional = (
        sales[open_price]
        .groupby(["sku_id", "region", "week_id"])
        .agg(units=("units", "sum"), price=("price_paid", "mean"), mechanism=("mechanism", "first"))
        .reset_index()
        .merge(default_dataset.products[["sku_id", "base_price"]])
        .merge(default_dataset.competitor_prices)
    )
    estimates, truths = [], []
    for sku_id, rows in regional.groupby("sku_id"):
        y = np.log(rows["units"] + 0.5).to_numpy()
        design = pd.get_dummies(rows[["region", "mechanism"]].fillna("none"), dtype=float)
        design = design.drop(columns=["mechanism_none"], errors="ignore")
        design.insert(0, "log_price", np.log(rows["price"] / rows["base_price"]))
        design.insert(1, "log_cpi", np.log(rows["competitor_price"] / rows["price"]))
        estimates.append(np.linalg.lstsq(design.to_numpy(), y, rcond=None)[0][0])
        truth = next(s for s in default_dataset.ground_truth.skus if s.sku_id == sku_id)
        truths.append(np.mean(list(truth.elasticity.values())))

    assert np.mean(estimates) == pytest.approx(np.mean(truths), rel=0.35)


def test_referential_integrity_and_no_negative_prices_or_units(
    small_dataset: GeneratedDataset,
) -> None:
    skus = set(small_dataset.products["sku_id"])
    stores = set(small_dataset.stores["store_id"])
    regions = set(small_dataset.stores["region"])
    sales = small_dataset.sales_weekly
    promos = small_dataset.promotions_history
    competitors = small_dataset.competitor_prices

    assert set(sales["sku_id"]) <= skus
    assert set(sales["store_id"]) <= stores
    assert set(promos["sku_id"]) <= skus
    assert set(promos["region"]) <= regions
    assert set(promos["bundle_sku_id"].dropna()) <= skus
    assert set(competitors["sku_id"]) <= skus
    assert set(competitors["region"]) <= regions
    assert (sales["units"] >= 0).all()
    assert (sales["price_paid"] > 0).all()
    assert (competitors["competitor_price"] > 0).all()
    assert promos["promo_id"].is_unique


def test_competitor_prices_cover_history_only(small_dataset: GeneratedDataset) -> None:
    competitors = small_dataset.competitor_prices

    assert competitors["week_id"].max() == small_dataset.config.history_weeks - 1
    assert competitors["competitor_on_promo"].any()


def test_one_region_has_an_aggressive_competitor_on_kvis(default_dataset: GeneratedDataset) -> None:
    competitors = default_dataset.competitor_prices.merge(
        default_dataset.products[["sku_id", "base_price", "is_kvi"]]
    )
    kvis = competitors[competitors["is_kvi"]]
    price_index = (kvis["competitor_price"] / kvis["base_price"]).groupby(kvis["region"]).mean()
    aggressive = default_dataset.config.competitors.aggressive_region.value

    assert price_index.idxmin() == aggressive
    assert price_index[aggressive] < price_index.drop(aggressive).min() - 0.03
