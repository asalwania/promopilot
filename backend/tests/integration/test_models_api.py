"""The models API against real Postgres: list, retrain, and the new version going live (#29)."""

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.community.postgres import PostgresContainer

from promopilot.api.main import create_app
from promopilot.api.models import ModelService
from promopilot.data import RetailData, load_dataset
from promopilot.datagen import GeneratedDataset, write
from promopilot.models.demand import DemandModel
from promopilot.models.registry import LatestModel, ModelKind, ModelRegistry
from tests.offline import offline_sessions

pytestmark = pytest.mark.integration

HISTORY_WEEKS = 52  # small_config


class HealthyProbe:
    async def is_healthy(self) -> bool:
        return True


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


@asynccontextmanager
async def running_api(url: str, model_dir: Path) -> AsyncIterator[AsyncClient]:
    """The API as build_app wires it: one registry behind /health, the list and retrain."""
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.exec_driver_sql("TRUNCATE model_registry")
    registry = ModelRegistry(engine, model_dir)
    live = LatestModel(registry, ModelKind.DEMAND, DemandModel)
    app = create_app(
        database_probe=HealthyProbe(),
        model_status=live,
        sessions=offline_sessions(),
        models=ModelService(registry=registry, data=RetailData(engine), live=live),
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        await engine.dispose()


async def test_an_empty_registry_lists_no_models(postgres_url: str, tmp_path: Path) -> None:
    async with running_api(postgres_url, tmp_path) as client:
        response = await client.get("/api/models")

    assert response.status_code == 200
    assert response.json() == {"models": []}


async def test_retrain_registers_a_new_version_that_becomes_the_latest_and_live(
    postgres_url: str, tmp_path: Path
) -> None:
    async with running_api(postgres_url, tmp_path) as client:
        missing = (await client.get("/health")).json()
        first = await client.post("/api/models/retrain")
        second = await client.post("/api/models/retrain")
        listed = await client.get("/api/models")
        health = (await client.get("/health")).json()

    assert missing["checks"]["model_registry"] == "missing"
    assert first.status_code == 201
    assert second.status_code == 201
    created = second.json()
    assert created["kind"] == "demand"
    assert created["version"] == 2
    assert created["as_of_week"] == HISTORY_WEEKS
    assert created["live"] is True
    assert "baseline_wape_region_sku" in created["metrics"]
    assert "artifact_path" not in created
    models = listed.json()["models"]
    assert [model["version"] for model in models] == [2, 1]
    assert [model["live"] for model in models] == [True, False]
    assert models[0] == created
    assert models[1]["model_id"] == first.json()["model_id"]
    assert health["checks"]["model_registry"] == "ok"


async def test_retrain_swaps_the_model_the_api_already_loaded(
    postgres_url: str, tmp_path: Path
) -> None:
    engine = create_async_engine(postgres_url)
    try:
        async with running_api(postgres_url, tmp_path) as client:
            await client.post("/api/models/retrain")
            registry = ModelRegistry(engine, tmp_path)
            live = LatestModel(registry, ModelKind.DEMAND, DemandModel)
            service = ModelService(registry=registry, data=RetailData(engine), live=live)
            loaded_before = await live.get()
            retrained = await service.retrain()
            loaded_after = await live.get()
    finally:
        await engine.dispose()

    assert loaded_before is not None
    assert loaded_before[0].version == 1
    assert loaded_after is not None
    assert loaded_after[0].model_id == retrained.model_id
    assert loaded_after[0].version == 2
