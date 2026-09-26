"""Regional competitor price series over history and horizon (SPEC §8.3)."""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from promopilot.datagen.config import GeneratorConfig
from promopilot.domain import Region


@dataclass(frozen=True)
class CompetitorSeries:
    prices: dict[Region, NDArray[np.float64]]
    """Per region, shape (total weeks, skus) in products order."""
    on_promo: dict[Region, NDArray[np.bool_]]


def generate_competitor_series(
    config: GeneratorConfig, products: pd.DataFrame, rng: np.random.Generator
) -> CompetitorSeries:
    competitors = config.competitors
    base = products["base_price"].to_numpy()
    is_kvi = products["is_kvi"].to_numpy()
    weeks, n = config.total_weeks, len(products)
    prices, on_promo = {}, {}
    for region in config.regions:
        aggressive = region is competitors.aggressive_region
        level = rng.uniform(*competitors.price_level, size=n)
        if aggressive:
            level = np.where(is_kvi, rng.uniform(*competitors.aggressive_kvi_price_level, n), level)
        start_probability = (
            competitors.aggressive_promo_probability
            if aggressive
            else competitors.promo_probability
        )
        promo = np.zeros((weeks, n), dtype=bool)
        depth = np.zeros((weeks, n))
        starts = rng.random((weeks, n)) < start_probability
        lengths = rng.integers(
            competitors.promo_weeks[0], competitors.promo_weeks[1] + 1, (weeks, n)
        )
        depths = rng.uniform(*competitors.promo_depth, size=(weeks, n))
        for week, sku in zip(*np.nonzero(starts), strict=True):
            span = slice(week, week + lengths[week, sku])
            promo[span, sku] = True
            depth[span, sku] = depths[week, sku]
        noise = rng.normal(0, competitors.weekly_noise_sd, size=(weeks, n))
        prices[region] = np.round(base * level * (1 + noise) * (1 - depth), 2)
        on_promo[region] = promo
    return CompetitorSeries(prices=prices, on_promo=on_promo)


def competitor_prices_table(
    config: GeneratorConfig, products: pd.DataFrame, series: CompetitorSeries
) -> pd.DataFrame:
    """The visible history only; future competitor prices live in the ground truth."""
    weeks, n = config.history_weeks, len(products)
    frames = [
        pd.DataFrame(
            {
                "week_id": np.repeat(np.arange(weeks), n),
                "region": region.value,
                "sku_id": np.tile(products["sku_id"].to_numpy(), weeks),
                "competitor_price": series.prices[region][:weeks].ravel(),
                "competitor_on_promo": series.on_promo[region][:weeks].ravel(),
            }
        )
        for region in config.regions
    ]
    return pd.concat(frames, ignore_index=True)
