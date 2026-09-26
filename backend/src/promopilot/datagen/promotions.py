"""Historical promotions: random mechanism, depth, duration and target segment (SPEC §8.1)."""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from promopilot.datagen.config import GeneratorConfig
from promopilot.datagen.truth import MECHANISMS, SEGMENTS, GroundTruth
from promopilot.domain import Mechanism, Region, TargetSegment
from promopilot.economics import effective_unit_price

MEAN_DURATION = 2.5  # durations are uniform on 1..4 weeks


@dataclass(frozen=True)
class RegionScenario:
    """What each segment paid and which mechanism applied, shape (weeks, segments, skus)."""

    prices: NDArray[np.float64]
    mechanisms: NDArray[np.int_]
    promo: NDArray[np.int_]
    """(weeks, skus): index into the promotions table of the promotion covering the SKU, or -1."""


def generate_promotions(
    config: GeneratorConfig,
    products: pd.DataFrame,
    truth: GroundTruth,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, dict[Region, RegionScenario]]:
    promotions = config.promotions
    weeks, n = config.history_weeks, len(products)
    sku_ids = list(products["sku_id"])
    index = {sku_id: i for i, sku_id in enumerate(sku_ids)}
    base = products["base_price"].to_numpy(dtype=float)
    partners: dict[int, list[int]] = {i: [] for i in range(n)}
    for a, b in truth.complement_pairs:
        partners[index[a]].append(index[b])
        partners[index[b]].append(index[a])
    mechanisms = list(promotions.mechanism_weights)
    weights = np.array([promotions.mechanism_weights[m] for m in mechanisms])
    weights = weights / weights.sum()
    # A promotion cycle is: duration, then the minimum gap, then a geometric wait. Bundle
    # partners add a little on top; few SKUs have complements, so that is left out.
    cycle = MEAN_DURATION / promotions.share
    start_probability = 1 / (cycle - MEAN_DURATION - promotions.min_gap_weeks + 1)

    events: list[dict[str, object]] = []
    scenarios: dict[Region, RegionScenario] = {}
    for region in config.regions:
        prices = np.tile(base, (weeks, len(SEGMENTS), 1))
        codes = np.full(prices.shape, -1)
        promo = np.full((weeks, n), -1)
        for i in range(n):
            week = 0
            while week < weeks:
                if promo[week, i] >= 0 or rng.random() >= start_probability:
                    week += 1
                    continue
                duration = int(rng.integers(1, 5))
                free = promo[week : week + duration, i] < 0
                duration = int(np.argmin(free)) if not free.all() else len(free)
                span = slice(week, week + duration)
                mechanism = mechanisms[rng.choice(len(mechanisms), p=weights)]
                partner = None
                if mechanism is Mechanism.BUNDLE:
                    options = [j for j in partners[i] if (promo[span, j] < 0).all()]
                    if options:
                        partner = options[rng.integers(len(options))]
                    else:
                        mechanism = Mechanism.PCT_OFF
                if mechanism is Mechanism.BOGO:
                    depth = 50
                elif mechanism is Mechanism.BUNDLE:
                    depth = int(rng.choice(promotions.bundle_depth_levels))
                else:
                    depth = int(rng.choice(promotions.depth_levels))
                if rng.random() < promotions.all_customers_share:
                    target = TargetSegment.ALL_CUSTOMERS
                    segments = list(range(len(SEGMENTS)))
                else:
                    g = int(rng.integers(len(SEGMENTS)))
                    target = TargetSegment(SEGMENTS[g].value)
                    segments = [g]

                event_id = len(events)
                for sku in [i] if partner is None else [i, partner]:
                    price = effective_unit_price(mechanism, float(base[sku]), depth)
                    for g in segments:
                        prices[span, g, sku] = price
                    promo[span, sku] = event_id
                for g in segments:
                    codes[span, g, i] = MECHANISMS.index(mechanism)
                events.append(
                    {
                        "sku_id": sku_ids[i],
                        "region": region.value,
                        "mechanism": mechanism.value,
                        "depth": depth,
                        "start_week": week,
                        "duration": duration,
                        "target_segment": target.value,
                        "bundle_sku_id": None if partner is None else sku_ids[partner],
                    }
                )
                week += duration + promotions.min_gap_weeks
        scenarios[region] = RegionScenario(prices=prices, mechanisms=codes, promo=promo)

    table = pd.DataFrame(
        events,
        columns=[
            "sku_id",
            "region",
            "mechanism",
            "depth",
            "start_week",
            "duration",
            "target_segment",
            "bundle_sku_id",
        ],
    )
    table.insert(0, "promo_id", [f"P{i + 1:06d}" for i in range(len(table))])
    return table, scenarios
