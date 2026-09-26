"""Draw the true demand parameters (the ground truth) for one seed."""

import json
from itertools import combinations

import numpy as np
import pandas as pd

from promopilot.datagen.competitors import CompetitorSeries
from promopilot.datagen.config import GeneratorConfig
from promopilot.datagen.truth import (
    SEGMENTS,
    CrossEffect,
    GroundTruth,
    HolidayWeek,
    SkuTruth,
    StoreTruth,
)
from promopilot.domain import Mechanism, Region, Segment


def draw_ground_truth(
    config: GeneratorConfig,
    products: pd.DataFrame,
    stores: pd.DataFrame,
    calendar: pd.DataFrame,
    competitors: CompetitorSeries,
    rng: np.random.Generator,
) -> GroundTruth:
    demand = config.demand
    subcategories = products["subcategory"].unique()
    sub_beta = dict(
        zip(
            subcategories,
            rng.uniform(*demand.elasticity_subcategory_mean, len(subcategories)),
            strict=True,
        )
    )
    sub_amplitude = dict(
        zip(subcategories, rng.uniform(*demand.season_amplitude, len(subcategories)), strict=True)
    )
    sub_phase = dict(zip(subcategories, rng.uniform(0, 52, len(subcategories)), strict=True))
    low, high = np.log(demand.base_weekly_units)

    skus = []
    for row in products.itertuples():
        kvi = bool(row.is_kvi)
        beta = sub_beta[row.subcategory] + rng.normal(0, demand.elasticity_sku_sd)
        beta += demand.kvi_elasticity_shift if kvi else 0.0
        base_level = rng.uniform(low, high) + (np.log(demand.kvi_volume_multiplier) if kvi else 0)
        gamma = rng.uniform(*demand.competitor_sensitivity)
        skus.append(
            SkuTruth(
                sku_id=str(row.sku_id),
                category=str(row.category),
                subcategory=str(row.subcategory),
                reference_price=float(row.base_price),  # type: ignore[arg-type]
                base_level=float(base_level),
                season_amplitude=float(sub_amplitude[row.subcategory]),
                season_phase_week=float(sub_phase[row.subcategory]),
                elasticity={
                    g: float(
                        np.clip(
                            beta * demand.segment_elasticity_multiplier[g],
                            *demand.elasticity_bounds,
                        )
                    )
                    for g in SEGMENTS
                },
                competitor_sensitivity=float(
                    gamma * (demand.kvi_competitor_multiplier if kvi else 1)
                ),
                mechanism_effect={
                    m: float(rng.uniform(*demand.mechanism_effect[m])) for m in Mechanism
                },
                pull_forward=float(rng.uniform(*demand.pull_forward)),
                dispersion=float(rng.uniform(*demand.dispersion)),
            )
        )

    store_truths = [
        StoreTruth(
            store_id=str(row.store_id),
            region=Region(str(row.region)),
            level=float(rng.normal(0, demand.store_level_sd)),
            segment_mix={Segment(k): v for k, v in json.loads(str(row.segment_mix)).items()},
        )
        for row in stores.itertuples()
    ]
    categories = list(products["category"].unique())
    holiday_names = sorted({h.name for h in config.holidays})
    substitute_pairs, complement_pairs, cross_effects = _relations(config, products, rng)
    return GroundTruth(
        start_date=config.start_date,
        history_weeks=config.history_weeks,
        horizon_weeks=config.horizon_weeks,
        pull_forward_window_weeks=demand.pull_forward_window_weeks,
        skus=skus,
        stores=store_truths,
        segment_affinity={
            c: {g: float(rng.normal(0, demand.segment_affinity_sd)) for g in SEGMENTS}
            for c in categories
        },
        holiday_sensitivity={
            c: {h: float(rng.uniform(*demand.holiday_sensitivity)) for h in holiday_names}
            for c in categories
        },
        holidays={
            region: [
                HolidayWeek(
                    name=None if pd.isna(row.holiday_name) else str(row.holiday_name),
                    intensity=float(row.holiday_intensity),  # type: ignore[arg-type]
                )
                for row in calendar[calendar["region"] == region.value].itertuples()
            ]
            for region in config.regions
        },
        competitor_prices={
            region: {
                sku_id: [float(p) for p in competitors.prices[region][:, i]]
                for i, sku_id in enumerate(products["sku_id"])
            }
            for region in config.regions
        },
        cross_effects=cross_effects,
        substitute_pairs=substitute_pairs,
        complement_pairs=complement_pairs,
    )


def _relations(
    config: GeneratorConfig, products: pd.DataFrame, rng: np.random.Generator
) -> tuple[list[tuple[str, str]], list[tuple[str, str]], list[CrossEffect]]:
    demand = config.demand
    substitutes: list[tuple[str, str]] = []
    for _, group in products.groupby("subcategory", sort=True):
        for a, b in combinations(group["sku_id"], 2):
            if rng.random() < demand.substitute_share:
                substitutes.append((a, b))

    by_category = {c: list(g["sku_id"]) for c, g in products.groupby("category", sort=True)}
    candidates = [
        (a, b)
        for first, second in demand.complement_categories
        if first in by_category and second in by_category
        for a in by_category[first]
        for b in by_category[second]
    ]
    if config.complement_pairs > len(candidates):
        raise ValueError(
            f"{config.complement_pairs} complement pairs requested but only "
            f"{len(candidates)} cross-category candidates exist"
        )
    picked = rng.choice(len(candidates), size=config.complement_pairs, replace=False)
    complements = [candidates[i] for i in sorted(picked)]

    effects = []
    for pairs, theta_range in (
        (substitutes, demand.substitute_theta),
        (complements, demand.complement_theta),
    ):
        for a, b in pairs:
            effects.append(
                CrossEffect(sku_id=a, other_sku_id=b, theta=float(rng.uniform(*theta_range)))
            )
            effects.append(
                CrossEffect(sku_id=b, other_sku_id=a, theta=float(rng.uniform(*theta_range)))
            )
    return substitutes, complements, effects
