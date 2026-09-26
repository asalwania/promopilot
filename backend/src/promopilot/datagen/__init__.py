"""Synthetic retail data with hidden ground truth (SPEC §8, ADR 0003).

Only promopilot.datagen and promopilot.evals may touch the ground truth.
"""

from promopilot.datagen.config import GeneratorConfig, load_config
from promopilot.datagen.dataset import GeneratedDataset
from promopilot.datagen.generator import generate
from promopilot.datagen.writer import DatasetPaths, write

__all__ = [
    "DatasetPaths",
    "GeneratedDataset",
    "GeneratorConfig",
    "generate",
    "load_config",
    "write",
]
