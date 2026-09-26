"""write(dataset, out_dir): Parquet tables in generated/, ground truth JSON in ground_truth/."""

from dataclasses import dataclass, fields
from pathlib import Path

import pandas as pd

from promopilot.datagen.dataset import GeneratedDataset

GENERATED_DIR = "generated"
GROUND_TRUTH_DIR = "ground_truth"


@dataclass(frozen=True)
class DatasetPaths:
    tables: dict[str, Path]
    ground_truth: Path


def write(dataset: GeneratedDataset, out_dir: Path) -> DatasetPaths:
    """Write every table and the ground truth; the same dataset gives byte-identical files."""
    generated = out_dir / GENERATED_DIR
    truth_dir = out_dir / GROUND_TRUTH_DIR
    generated.mkdir(parents=True, exist_ok=True)
    truth_dir.mkdir(parents=True, exist_ok=True)
    tables = {}
    for field in fields(dataset):
        table = getattr(dataset, field.name)
        if isinstance(table, pd.DataFrame):
            path = generated / f"{field.name}.parquet"
            table.to_parquet(path, index=False, compression="zstd")
            tables[field.name] = path
    truth_path = truth_dir / "ground_truth.json"
    truth_path.write_text(dataset.ground_truth.model_dump_json(), encoding="utf-8")
    return DatasetPaths(tables=tables, ground_truth=truth_path)
