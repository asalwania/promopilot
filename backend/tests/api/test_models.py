"""`POST /api/models/retrain` error contract, without a database (ADR 0026).

The happy paths (list, retrain, the new version going live) run against real Postgres in
tests/integration/test_models_api.py.
"""

import asyncio
from pathlib import Path

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine

from promopilot.api.main import create_app
from promopilot.api.models import ModelService
from promopilot.data import RetailData
from promopilot.models.demand import DemandModel
from promopilot.models.registry import LatestModel, ModelKind, ModelRegistry
from tests.offline import NoModel, offline_sessions

# Creating an engine does not connect; these tests never reach the database.
ENGINE = create_async_engine("postgresql+asyncpg://unused@127.0.0.1:1/unused")


class NoData(RetailData):
    """Nothing loaded: what `RetailData` says before `make data`."""

    async def default_as_of_week(self) -> int:
        raise LookupError("no sales history is loaded; run `make data`")


class GatedNoData(NoData):
    """Holds the first retrain inside its data read until the test opens the gate."""

    def __init__(self) -> None:
        super().__init__(ENGINE)
        self.entered = asyncio.Event()
        self.gate = asyncio.Event()

    async def default_as_of_week(self) -> int:
        self.entered.set()
        await self.gate.wait()
        return await super().default_as_of_week()


class HealthyProbe:
    async def is_healthy(self) -> bool:
        return True


def client_for(data: RetailData) -> AsyncClient:
    registry = ModelRegistry(ENGINE, Path("unused"))
    models = ModelService(
        registry=registry,
        data=data,
        live=LatestModel(registry, ModelKind.DEMAND, DemandModel),
    )
    app = create_app(
        database_probe=HealthyProbe(),
        model_status=NoModel(),
        sessions=offline_sessions(),
        models=models,
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_retrain_without_loaded_data_is_409_saying_to_run_make_data() -> None:
    async with client_for(NoData(ENGINE)) as client:
        response = await client.post("/api/models/retrain")

    assert response.status_code == 409
    assert "make data" in response.json()["detail"]


async def test_a_retrain_while_one_is_running_is_409() -> None:
    data = GatedNoData()
    async with client_for(data) as client:
        first = asyncio.create_task(client.post("/api/models/retrain"))
        await data.entered.wait()
        second = await client.post("/api/models/retrain")
        data.gate.set()
        finished = await first
        after = await client.post("/api/models/retrain")

    assert second.status_code == 409
    assert "already running" in second.json()["detail"]
    assert finished.status_code == 409  # the gated retrain itself found no data
    assert "make data" in after.json()["detail"]  # a failed retrain frees the slot
