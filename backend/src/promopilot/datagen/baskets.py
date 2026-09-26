"""Basket transactions whose co-occurrence reflects the true complement pairs (SPEC §9.2)."""

import json

import numpy as np
import pandas as pd

from promopilot.datagen.config import GeneratorConfig
from promopilot.datagen.truth import SEGMENTS, GroundTruth


def generate_baskets(
    config: GeneratorConfig,
    stores: pd.DataFrame,
    truth: GroundTruth,
    rng: np.random.Generator,
) -> pd.DataFrame:
    count = config.baskets
    sku_ids = np.array([sku.sku_id for sku in truth.skus])
    index = {sku_id: i for i, sku_id in enumerate(sku_ids)}
    # Popularity per segment: the true base level plus the segment's category taste.
    popularity = np.array(
        [
            [np.exp(sku.base_level + truth.segment_affinity[sku.category][g]) for sku in truth.skus]
            for g in SEGMENTS
        ]
    )
    popularity /= popularity.sum(axis=1, keepdims=True)
    complements: list[list[int]] = [[] for _ in sku_ids]
    for a, b in truth.complement_pairs:
        complements[index[a]].append(index[b])
        complements[index[b]].append(index[a])

    store_rows = rng.integers(len(stores), size=count)
    mixes = np.array(
        [[json.loads(str(mix))[g.value] for g in SEGMENTS] for mix in stores["segment_mix"]]
    )
    cumulative = mixes[store_rows].cumsum(axis=1)
    segment = (rng.random((count, 1)) > cumulative).sum(axis=1).clip(max=len(SEGMENTS) - 1)
    week = rng.integers(config.history_weeks, size=count)
    sizes = 1 + rng.poisson(config.basket_contents.mean_extra_items, size=count)

    basket_of_item = np.repeat(np.arange(count), sizes)
    items = np.empty(len(basket_of_item), dtype=np.int64)
    item_segment = segment[basket_of_item]
    for g in range(len(SEGMENTS)):
        chosen = item_segment == g
        items[chosen] = rng.choice(len(sku_ids), size=int(chosen.sum()), p=popularity[g])

    has_complement = np.array([len(c) > 0 for c in complements])
    attach = has_complement[items] & (
        rng.random(len(items)) < config.basket_contents.complement_attach
    )
    picks = rng.random(int(attach.sum()))
    attached = np.array(
        [
            complements[i][int(p * len(complements[i]))]
            for i, p in zip(items[attach], picks, strict=True)
        ],
        dtype=np.int64,
    )
    all_baskets = np.concatenate([basket_of_item, basket_of_item[attach]])
    all_items = np.concatenate([items, attached])
    keys = np.unique(all_baskets * len(sku_ids) + all_items)  # sorted, one per basket and SKU
    boundaries = np.searchsorted(keys // len(sku_ids), np.arange(1, count))
    contents = [sku_ids[chunk].tolist() for chunk in np.split(keys % len(sku_ids), boundaries)]

    return pd.DataFrame(
        {
            "basket_id": [f"B{i + 1:07d}" for i in range(count)],
            "store_id": stores["store_id"].to_numpy()[store_rows],
            "week_id": week,
            "segment": np.array([g.value for g in SEGMENTS])[segment],
            "sku_ids": contents,
        }
    )
