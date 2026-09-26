"""Substitutes and complements (SPEC §9.2): detection against known truth and hand-built cases."""

from itertools import combinations

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from statsmodels.stats.multitest import multipletests

from promopilot.datagen import GeneratedDataset, generate, load_config
from promopilot.models import demand, relations
from promopilot.models.demand import DemandHistory, DemandModel
from promopilot.models.relations import Relations, RelationsConfig
from tests.conftest import RELATIONS_OVERRIDES, history_of
from tests.unit.models.test_baseline import poisoned

AS_OF = 52  # the first week after the small world's 52 history weeks
SEED = 7

MIN_PRECISION = 0.8
MIN_RECALL = 0.7
"""Detection thresholds on the relations fixture (ADR 0029); SPEC §12.2 sets the same targets
for the full dataset, which E9 reports."""


@pytest.fixture(scope="module")
def demand_model(small_history: DemandHistory) -> DemandModel:
    return demand.fit(small_history, as_of_week=AS_OF, seed=SEED)


@pytest.fixture(scope="module")
def small_relations(
    small_dataset: GeneratedDataset, small_history: DemandHistory, demand_model: DemandModel
) -> Relations:
    return relations.fit(
        small_history, small_dataset.baskets, demand_model, as_of_week=AS_OF, seed=SEED
    )


def within_subcategory_pairs(history: DemandHistory) -> list[tuple[str, str]]:
    products = history.products.sort_values("sku_id")
    return [
        (a, b)
        for _, group in products.groupby("subcategory")
        for a, b in combinations(group["sku_id"], 2)
    ]


def found_substitutes(fitted: Relations, sku_ids: list[str]) -> set[tuple[str, str]]:
    return {
        (min(sku, other), max(sku, other))
        for sku in sku_ids
        for other in fitted.substitutes(sku)["sku_id"]
    }


def found_complements(fitted: Relations, sku_ids: list[str]) -> set[tuple[str, str]]:
    return {
        (min(sku, other), max(sku, other))
        for sku in sku_ids
        for other in fitted.complements(sku)["sku_id"]
    }


# --- complements from basket lift -------------------------------------------------------


def unpromoted(history: DemandHistory) -> DemandHistory:
    """The same history with no promotions: no price ever moves, so no cross effect is
    estimable and basket lift alone decides complements."""
    return DemandHistory(
        products=history.products,
        stores=history.stores,
        calendar=history.calendar,
        sales_weekly=history.sales_weekly,
        promotions_history=history.promotions_history.iloc[0:0],
        competitor_prices=history.competitor_prices,
    )


def hand_built_baskets(contents: list[list[str]], store_id: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "basket_id": [f"H{i:03d}" for i in range(len(contents))],
            "store_id": store_id,
            "week_id": 10,
            "segment": "Families",
            "sku_ids": contents,
        }
    )


def test_lift_and_support_are_computed_exactly_on_hand_built_baskets(
    small_history: DemandHistory, demand_model: DemandModel
) -> None:
    a, b, c, d, e = sorted(small_history.products["sku_id"])[:5]
    contents = [[a, b], [a, b], [a], [b], [c, d], [c], [d], [e], [e], [e]]
    baskets = hand_built_baskets(contents, str(small_history.stores["store_id"].iloc[0]))

    fitted = relations.fit(
        unpromoted(small_history), baskets, demand_model, as_of_week=AS_OF, seed=SEED
    )

    # P(a and b) = 2/10, P(a) = P(b) = 3/10: lift = 0.2 / 0.09.
    of_a = fitted.complements(a)
    assert list(of_a["sku_id"]) == [b]
    assert of_a["support"].iloc[0] == pytest.approx(0.2)
    assert of_a["lift"].iloc[0] == pytest.approx(0.2 / 0.09)
    assert list(fitted.complements(b)["sku_id"]) == [a]
    # P(c and d) = 1/10, P(c) = P(d) = 2/10: lift 2.5, and support 0.1 clears the minimum.
    assert fitted.complements(c)["lift"].iloc[0] == pytest.approx(2.5)
    assert fitted.complements(e).empty


def test_complements_need_lift_above_the_threshold_and_minimum_support(
    small_history: DemandHistory, demand_model: DemandModel
) -> None:
    a, b, c, d, e = sorted(small_history.products["sku_id"])[:5]
    contents = [[a, b], [a, b], [a], [b], [c, d], [c], [d], [e], [e], [e]]
    baskets = hand_built_baskets(contents, str(small_history.stores["store_id"].iloc[0]))

    strict = relations.fit(
        unpromoted(small_history),
        baskets,
        demand_model,
        as_of_week=AS_OF,
        seed=SEED,
        config=RelationsConfig(complement_min_lift=2.3, complement_min_support=0.15),
    )

    assert strict.complements(a).empty  # lift 2.22 is not above 2.3
    assert strict.complements(c).empty  # support 0.1 is below 0.15


# --- substitutes from cross-price regression --------------------------------------------


def test_a_substitute_needs_a_bh_q_below_005_and_the_minimum_effect_size(
    small_history: DemandHistory, small_relations: Relations
) -> None:
    pairs = within_subcategory_pairs(small_history)
    effects = [(pair, small_relations.cross_effect(*pair)) for pair in pairs]
    tested = [(pair, effect) for pair, effect in effects if effect is not None]
    p_values = np.array([effect.p_value for _, effect in tested])
    q_values = multipletests(p_values, method="fdr_bh")[1]
    minimum = RelationsConfig().substitute_min_theta

    expected = {
        pair
        for (pair, effect), q in zip(tested, q_values, strict=True)
        if q < 0.05 and effect.theta >= minimum
    }
    sku_ids = list(small_history.products["sku_id"])
    assert found_substitutes(small_relations, sku_ids) == expected
    assert len(tested) > len(expected) > 0
    # Cross effects are symmetric: one theta per unordered pair.
    (a, b), effect = tested[0]
    assert small_relations.cross_effect(b, a) == effect


def test_raising_the_minimum_effect_size_drops_smaller_substitutes(
    small_dataset: GeneratedDataset,
    small_history: DemandHistory,
    demand_model: DemandModel,
    small_relations: Relations,
) -> None:
    sku_ids = list(small_history.products["sku_id"])
    kept = found_substitutes(small_relations, sku_ids)
    theta: dict[tuple[str, str], float] = {}
    for sku_a, sku_b in kept:
        table = small_relations.substitutes(sku_a)
        theta[(sku_a, sku_b)] = float(table.loc[table["sku_id"] == sku_b, "theta"].iloc[0])
    weakest = min(kept, key=lambda pair: theta[pair])
    cut = theta[weakest] + 1e-6

    strict = relations.fit(
        small_history,
        small_dataset.baskets,
        demand_model,
        as_of_week=AS_OF,
        seed=SEED,
        config=RelationsConfig(substitute_min_theta=cut),
    )

    assert found_substitutes(strict, sku_ids) == {pair for pair in kept if theta[pair] >= cut}
    assert weakest not in found_substitutes(strict, sku_ids)


def test_substitutes_report_theta_with_its_standard_error(
    small_history: DemandHistory, small_relations: Relations
) -> None:
    sku_ids = list(small_history.products["sku_id"])
    sku = next(s for s in sku_ids if not small_relations.substitutes(s).empty)

    table = small_relations.substitutes(sku)

    assert list(table.columns) == ["sku_id", "theta", "std_error", "q_value"]
    assert (table["theta"] > 0).all()
    assert (table["std_error"] > 0).all()
    assert (table["q_value"] < 0.05).all()
    assert small_relations.cross_effect(sku, sku) is None


# --- leakage, determinism, registry metrics ---------------------------------------------


def test_fitting_ignores_data_at_or_after_the_as_of_week(
    small_dataset: GeneratedDataset,
    small_history: DemandHistory,
    demand_model: DemandModel,
    small_relations: Relations,
) -> None:
    baskets = small_dataset.baskets
    future = baskets.head(2_000).assign(week_id=AS_OF)
    future["basket_id"] = future["basket_id"] + "-future"
    sku_ids = list(small_history.products["sku_id"])
    future["sku_ids"] = [sku_ids[:2]] * len(future)  # a strong fake complement

    leaky = relations.fit(
        poisoned(small_history, AS_OF),
        pd.concat([baskets, future]),
        demand_model,
        as_of_week=AS_OF,
        seed=SEED,
    )

    for sku in sku_ids:
        assert_frame_equal(leaky.substitutes(sku), small_relations.substitutes(sku))
        assert_frame_equal(leaky.complements(sku), small_relations.complements(sku))
    assert leaky.metrics == small_relations.metrics


def test_fitting_is_deterministic_per_seed(
    small_dataset: GeneratedDataset,
    small_history: DemandHistory,
    demand_model: DemandModel,
    small_relations: Relations,
) -> None:
    again = relations.fit(
        small_history, small_dataset.baskets, demand_model, as_of_week=AS_OF, seed=SEED
    )

    for sku in small_history.products["sku_id"]:
        assert_frame_equal(again.substitutes(sku), small_relations.substitutes(sku))
        assert_frame_equal(again.complements(sku), small_relations.complements(sku))
        for other in small_history.products["sku_id"]:
            assert again.cross_effect(sku, other) == small_relations.cross_effect(sku, other)


def test_the_demand_model_must_share_the_as_of_week(
    small_dataset: GeneratedDataset, small_history: DemandHistory, demand_model: DemandModel
) -> None:
    with pytest.raises(ValueError, match="as-of week"):
        relations.fit(
            small_history, small_dataset.baskets, demand_model, as_of_week=AS_OF - 4, seed=SEED
        )


def test_the_registry_metrics_report_counts_and_thresholds(
    small_history: DemandHistory, small_relations: Relations
) -> None:
    metrics = small_relations.metrics
    sku_ids = list(small_history.products["sku_id"])
    config = RelationsConfig()

    assert metrics["substitute_pairs"] == len(found_substitutes(small_relations, sku_ids))
    assert metrics["complement_pairs"] == len(found_complements(small_relations, sku_ids))
    assert 0 < metrics["substitute_pairs_tested"] <= len(within_subcategory_pairs(small_history))
    assert metrics["complement_candidates"] >= metrics["complement_pairs"]
    assert metrics["baskets"] > 0
    assert metrics["substitute_max_q"] == config.substitute_max_q
    assert metrics["substitute_min_theta"] == config.substitute_min_theta
    assert metrics["complement_min_lift"] == config.complement_min_lift
    assert metrics["complement_min_support"] == config.complement_min_support
    assert metrics["complement_max_q"] == config.complement_max_q


# --- detection quality against datagen's in-memory ground truth (ADR 0010) --------------


@pytest.fixture(scope="module")
def relations_world() -> GeneratedDataset:
    return generate(load_config(overrides=RELATIONS_OVERRIDES), seed=5)


@pytest.fixture(scope="module")
def world_relations(relations_world: GeneratedDataset) -> Relations:
    history = history_of(relations_world)
    as_of = int(history.sales_weekly["week_id"].max()) + 1
    model = demand.fit(history, as_of_week=as_of, seed=3)
    return relations.fit(history, relations_world.baskets, model, as_of_week=as_of, seed=3)


def precision_recall(
    found: set[tuple[str, str]], true: set[tuple[str, str]]
) -> tuple[float, float]:
    hits = len(found & true)
    return hits / max(len(found), 1), hits / len(true)


@pytest.mark.model
def test_substitutes_are_detected_with_good_precision_and_recall(
    relations_world: GeneratedDataset, world_relations: Relations
) -> None:
    truth = relations_world.ground_truth
    true = {(min(a, b), max(a, b)) for a, b in truth.substitute_pairs}
    sku_ids = [sku.sku_id for sku in truth.skus]

    precision, recall = precision_recall(found_substitutes(world_relations, sku_ids), true)

    assert precision >= MIN_PRECISION
    assert recall >= MIN_RECALL


@pytest.mark.model
def test_complements_are_detected_with_good_precision_and_recall(
    relations_world: GeneratedDataset, world_relations: Relations
) -> None:
    truth = relations_world.ground_truth
    true = {(min(a, b), max(a, b)) for a, b in truth.complement_pairs}
    sku_ids = [sku.sku_id for sku in truth.skus]

    precision, recall = precision_recall(found_complements(world_relations, sku_ids), true)

    assert precision >= MIN_PRECISION
    assert recall >= MIN_RECALL
