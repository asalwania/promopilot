"""Weekly sales per store, SKU and segment, drawn from the true demand function."""

import numpy as np
import pandas as pd

from promopilot.datagen.config import GeneratorConfig
from promopilot.datagen.promotions import RegionScenario
from promopilot.datagen.truth import SEGMENTS, TrueDemand
from promopilot.domain import Region


def generate_sales(
    config: GeneratorConfig,
    demand: TrueDemand,
    promotions: pd.DataFrame,
    scenarios: dict[Region, RegionScenario],
    rng: np.random.Generator,
) -> pd.DataFrame:
    frames = []
    promo_columns = promotions[["mechanism", "depth", "target_segment"]]
    for region in config.regions:
        scenario = scenarios[region]
        expected = demand.expected_units(region, 0, scenario.prices, scenario.mechanisms)
        size = demand.dispersion  # (N,) broadcast over (S, W, G, N)
        units = rng.negative_binomial(size, size / (size + expected))  # (S, W, G, N)
        total = units.sum(axis=2)  # (S, W, N)
        paid = (units * scenario.prices).sum(axis=2)
        expected_paid = (expected * scenario.prices).sum(axis=2) / expected.sum(axis=2)
        price_paid = np.where(total > 0, paid / np.maximum(total, 1), expected_paid)

        stores, weeks, n = total.shape
        promo = np.broadcast_to(scenario.promo, (stores, weeks, n)).transpose(1, 0, 2).ravel()
        on_promo = promo >= 0
        details = promo_columns.iloc[np.where(on_promo, promo, 0)].reset_index(drop=True)
        details[~on_promo] = None
        by_segment = units.transpose(1, 0, 3, 2)  # (W, S, N, G)
        segment_units = pd.Series('{"' + SEGMENTS[0].value + '": ', index=range(total.size))
        for g, segment in enumerate(SEGMENTS):
            prefix = "" if g == 0 else ', "' + segment.value + '": '
            segment_units = segment_units + prefix + by_segment[..., g].ravel().astype(str)
        frames.append(
            pd.DataFrame(
                {
                    "week_id": np.repeat(np.arange(weeks), stores * n),
                    "store_id": np.tile(np.repeat(demand.store_ids(region), n), weeks),
                    "sku_id": np.tile(demand.sku_ids, weeks * stores),
                    "units": total.transpose(1, 0, 2).ravel(),
                    "price_paid": np.round(price_paid.transpose(1, 0, 2).ravel(), 2),
                    "on_promo": on_promo,
                    "mechanism": details["mechanism"],
                    "depth": details["depth"].astype("Int64"),
                    "target_segment": details["target_segment"],
                    "segment_units": segment_units + "}",
                }
            )
        )
    sales = pd.concat(frames, ignore_index=True)
    return sales.sort_values(["week_id", "store_id", "sku_id"], ignore_index=True)
