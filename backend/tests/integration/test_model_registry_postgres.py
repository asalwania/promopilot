"""The model registry against real Postgres: register -> list -> load latest (E4 seam 2)."""

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from pandas.testing import assert_frame_equal
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from promopilot.api.main import create_app
from promopilot.data import migrate
from promopilot.models import demand
from promopilot.models.demand import DemandHistory, DemandModel
from promopilot.models.registry import LatestModel, ModelKind, ModelRegistry
from tests.offline import offline_sessions

pytestmark = pytest.mark.integration

AS_OF = 52


@pytest.fixture(scope="module")
def postgres_url() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as postgres:
        yield postgres.get_connection_url()


@pytest.fixture
async def engine(postgres_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(postgres_url)
    await migrate(engine)
    async with engine.begin() as connection:
        await connection.exec_driver_sql("TRUNCATE model_registry")
    yield engine
    await engine.dispose()


@pytest.fixture(scope="module")
def model(small_history: DemandHistory) -> DemandModel:
    return demand.fit(small_history, as_of_week=AS_OF, seed=7)


async def test_registered_models_list_newest_first_and_the_latest_loads(
    engine: AsyncEngine, tmp_path: Path, model: DemandModel
) -> None:
    registry = ModelRegistry(engine, tmp_path)

    first = await registry.register(
        ModelKind.DEMAND, model, as_of_week=AS_OF - 1, metrics={"baseline_wape": 0.31}
    )
    second = await registry.register(
        ModelKind.DEMAND, model, as_of_week=AS_OF, metrics={"baseline_wape": 0.2875}
    )
    listed = await registry.list()
    latest = await registry.load_latest(ModelKind.DEMAND, DemandModel)

    assert [entry.version for entry in listed] == [2, 1]
    assert listed == [second, first]
    assert listed[0].metrics == {"baseline_wape": 0.2875}
    assert listed[0].as_of_week == AS_OF
    assert listed[0].trained_at >= listed[1].trained_at
    assert (tmp_path / listed[0].artifact_path).is_file()
    assert latest is not None
    entry, loaded = latest
    assert entry == second
    assert_frame_equal(loaded.baseline([AS_OF]), model.baseline([AS_OF]))


async def test_an_empty_registry_has_no_latest_model(engine: AsyncEngine, tmp_path: Path) -> None:
    registry = ModelRegistry(engine, tmp_path)

    assert await registry.list() == []
    assert await registry.load_latest(ModelKind.DEMAND, DemandModel) is None


class HealthyProbe:
    async def is_healthy(self) -> bool:
        return True


async def test_health_finds_a_model_registered_after_the_api_started(
    engine: AsyncEngine, tmp_path: Path, model: DemandModel
) -> None:
    registry = ModelRegistry(engine, tmp_path)
    latest = LatestModel(registry, ModelKind.DEMAND, DemandModel)
    app = create_app(
        database_probe=HealthyProbe(), model_status=latest, sessions=offline_sessions()
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        before = (await client.get("/health")).json()
        await registry.register(ModelKind.DEMAND, model, as_of_week=AS_OF, metrics={})
        after = (await client.get("/health")).json()

    assert before["checks"]["model_registry"] == "missing"
    assert after["checks"]["model_registry"] == "ok"
    assert await latest.get() is not None


async def test_a_registered_model_whose_artifact_is_gone_counts_as_missing(
    engine: AsyncEngine, tmp_path: Path, model: DemandModel
) -> None:
    registry = ModelRegistry(engine, tmp_path)
    entry = await registry.register(ModelKind.DEMAND, model, as_of_week=AS_OF, metrics={})
    (tmp_path / entry.artifact_path).unlink()

    assert not await LatestModel(registry, ModelKind.DEMAND, DemandModel).is_loaded()
