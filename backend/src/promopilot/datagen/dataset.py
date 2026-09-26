"""The in-memory generated dataset."""

from dataclasses import dataclass

import pandas as pd

from promopilot.datagen.config import GeneratorConfig
from promopilot.datagen.truth import GroundTruth


@dataclass(frozen=True)
class GeneratedDataset:
    """All SPEC §8.2 data tables for one seed and config, plus the hidden ground truth."""

    config: GeneratorConfig
    seed: int
    products: pd.DataFrame
    stores: pd.DataFrame
    calendar: pd.DataFrame
    competitor_prices: pd.DataFrame
    promotions_history: pd.DataFrame
    sales_weekly: pd.DataFrame
    ground_truth: GroundTruth
