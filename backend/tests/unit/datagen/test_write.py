import json
from pathlib import Path

import pandas as pd

from promopilot.datagen import GeneratedDataset, write
from promopilot.datagen.__main__ import main
from promopilot.datagen.truth import GroundTruth

TABLES = {
    "products",
    "stores",
    "calendar",
    "sales_weekly",
    "promotions_history",
    "inventory",
    "competitor_prices",
    "baskets",
}


def test_write_puts_tables_in_generated_and_truth_in_ground_truth(
    small_dataset: GeneratedDataset, tmp_path: Path
) -> None:
    paths = write(small_dataset, tmp_path)

    assert set(paths.tables) == TABLES
    assert all(path.parent == tmp_path / "generated" for path in paths.tables.values())
    assert paths.ground_truth == tmp_path / "ground_truth" / "ground_truth.json"
    written = pd.read_parquet(paths.tables["sales_weekly"])
    pd.testing.assert_frame_equal(written, small_dataset.sales_weekly, check_dtype=False)
    truth = GroundTruth.model_validate_json(paths.ground_truth.read_text(encoding="utf-8"))
    assert truth == small_dataset.ground_truth


def test_writing_the_same_dataset_twice_gives_byte_identical_files(
    small_dataset: GeneratedDataset, tmp_path: Path
) -> None:
    first = write(small_dataset, tmp_path / "a")
    second = write(small_dataset, tmp_path / "b")

    for name, path in first.tables.items():
        assert path.read_bytes() == second.tables[name].read_bytes(), name
    assert first.ground_truth.read_bytes() == second.ground_truth.read_bytes()


def test_the_cli_generates_and_writes_with_config_overrides(tmp_path: Path) -> None:
    config = tmp_path / "tiny.yaml"
    config.write_text(
        json.dumps(
            {
                "catalogue": {"categories_limit": 2, "skus_per_category": 4},
                "regions": ["East"],
                "stores_per_region": 2,
                "history_weeks": 12,
                "horizon_weeks": 4,
                "baskets": 100,
                "complement_pairs": 2,
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(["--config", str(config), "--seed", "5", "--out", str(tmp_path / "data")])

    assert exit_code == 0
    products = pd.read_parquet(tmp_path / "data" / "generated" / "products.parquet")
    assert len(products) == 8
    assert (tmp_path / "data" / "ground_truth" / "ground_truth.json").exists()
