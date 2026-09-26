"""Regions, stores with segment mix, and the weekly festival calendar."""

import json
from datetime import timedelta

import numpy as np
import pandas as pd

from promopilot.datagen.config import GeneratorConfig
from promopilot.domain import Segment

SEGMENTS = list(Segment)


def generate_stores(config: GeneratorConfig, rng: np.random.Generator) -> pd.DataFrame:
    base = np.array([config.segment_mix.base[segment] for segment in SEGMENTS])
    base = base / base.sum()
    rows = []
    for region in config.regions:
        regional = rng.dirichlet(config.segment_mix.region_concentration * base)
        cities = config.cities[region]
        for number in range(1, config.stores_per_region + 1):
            mix = rng.dirichlet(config.segment_mix.store_concentration * regional)
            rows.append(
                {
                    "store_id": f"{region.value[0]}{number:02d}",
                    "region": region.value,
                    "city": cities[(number - 1) % len(cities)],
                    "segment_mix": json.dumps(
                        {s.value: float(share) for s, share in zip(SEGMENTS, mix, strict=True)}
                    ),
                }
            )
    return pd.DataFrame(rows)


def generate_calendar(config: GeneratorConfig) -> pd.DataFrame:
    """One row per week and region; festivals lift their week and, less, the week before."""
    weeks = config.total_weeks
    rows = []
    for region in config.regions:
        name: list[str | None] = [None] * weeks
        intensity = [0.0] * weeks
        for holiday in config.holidays:
            if holiday.regions is not None and region not in holiday.regions:
                continue
            for day in holiday.dates:
                week = (day - config.start_date).days // 7
                for offset, level in (
                    (0, holiday.intensity),
                    (-1, holiday.intensity * config.holiday_lead_in),
                ):
                    w = week + offset
                    if 0 <= w < weeks and level > intensity[w]:
                        name[w], intensity[w] = holiday.name, level
        for w in range(weeks):
            rows.append(
                {
                    "week_id": w,
                    "week_start": config.start_date + timedelta(weeks=w),
                    "region": region.value,
                    "holiday_name": name[w],
                    "holiday_intensity": intensity[w],
                }
            )
    return pd.DataFrame(rows)
