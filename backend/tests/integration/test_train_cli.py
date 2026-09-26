"""`make train` against real Postgres: fit on the loaded data, then register (E4 seam 4)."""

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.community.postgres import PostgresContainer

from promopilot.data import load_dataset
from promopilot.datagen import GeneratedDataset, write
from promopilot.models.__main__ import run
from promopilot.models.demand import DemandModel
from promopilot.models.registry import ModelKind, ModelRegistry
from promopilot.models.relations import Relations

pytestmark = pytest.mark.integration

HISTORY_WEEKS = 52  # small_config


@pytest.fixture(scope="module")
def postgres_url(
    small_dataset: GeneratedDataset, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[str]:
    data_dir: Path = tmp_path_factory.mktemp("data")
    write(small_dataset, data_dir)
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as postgres:
        url = postgres.get_connection_url()
        asyncio.run(load_dataset(data_dir, url))
        yield url


async def test_train_fits_demand_then_relations_on_loaded_data_and_registers_both(
    postgres_url: str, tmp_path: Path
) -> None:
    exit_code = await run(
        ["--database-url", postgres_url, "--model-dir", str(tmp_path), "--seed", "7"]
    )

    engine = create_async_engine(postgres_url)
    try:
        registry = ModelRegistry(engine, tmp_path)
        [entry] = await registry.list(ModelKind.DEMAND)
        [relations_entry] = await registry.list(ModelKind.RELATIONS)
        latest = await registry.load_latest(ModelKind.DEMAND, DemandModel)
        latest_relations = await registry.load_latest(ModelKind.RELATIONS, Relations)
    finally:
        await engine.dispose()
    assert exit_code == 0
    assert (entry.kind, entry.version, entry.as_of_week) == (ModelKind.DEMAND, 1, HISTORY_WEEKS)
    assert "baseline_wape_region_sku" in entry.metrics
    assert latest is not None
    assert latest[1].as_of_week == HISTORY_WEEKS
    assert (relations_entry.version, relations_entry.as_of_week) == (1, HISTORY_WEEKS)
    assert relations_entry.metrics["demand_version"] == entry.version
    assert relations_entry.metrics["substitute_min_theta"] == 0.1
    assert "complement_pairs" in relations_entry.metrics
    assert latest_relations is not None
    assert latest_relations[1].as_of_week == HISTORY_WEEKS


async def test_train_takes_an_explicit_as_of_week(postgres_url: str, tmp_path: Path) -> None:
    await run(
        [
            "--database-url",
            postgres_url,
            "--model-dir",
            str(tmp_path),
            "--as-of-week",
            "40",
            "--seed",
            "7",
        ]
    )

    engine = create_async_engine(postgres_url)
    try:
        entries = await ModelRegistry(engine, tmp_path).list()
    finally:
        await engine.dispose()
    assert {entry.kind for entry in entries[:2]} == {ModelKind.DEMAND, ModelKind.RELATIONS}
    assert [entry.as_of_week for entry in entries[:2]] == [40, 40]
