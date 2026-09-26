"""The API loads the latest registered demand model at startup and injects it into its tools."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.community.postgres import PostgresContainer

from promopilot.agents.tools import ToolOk, ToolRegistry
from promopilot.agents.tools.estimate_demand import EstimateDemandOutput
from promopilot.api.main import build_app
from promopilot.data import migrate
from promopilot.models import demand
from promopilot.models.demand import DemandHistory
from promopilot.models.registry import ModelKind, ModelRegistry

pytestmark = pytest.mark.integration

AS_OF = 52


@pytest.fixture(scope="module")
def postgres_url() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as postgres:
        yield postgres.get_connection_url()


async def test_the_api_serves_estimate_demand_from_the_latest_registered_model(
    postgres_url: str,
    tmp_path: Path,
    small_history: DemandHistory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine(postgres_url)
    try:
        await migrate(engine)
        registry = ModelRegistry(engine, tmp_path)
        model = demand.fit(small_history, as_of_week=AS_OF, seed=7)
        await registry.register(ModelKind.DEMAND, model, as_of_week=AS_OF, metrics={})
        latest = await registry.register(ModelKind.DEMAND, model, as_of_week=AS_OF, metrics={})
    finally:
        await engine.dispose()
    monkeypatch.setenv("DATABASE_URL", postgres_url)
    monkeypatch.setenv("MODEL_DIR", str(tmp_path))
    sku_id = str(small_history.products["sku_id"].iloc[0])

    app = build_app()
    async with app.router.lifespan_context(app):
        tools = app.state.tools
        assert isinstance(tools, ToolRegistry)
        result = await tools.call(
            "estimate_demand",
            {
                "options": [
                    {
                        "sku_id": sku_id,
                        "region": "North",
                        "mechanism": "PCT_OFF",
                        "depth_pct": 20,
                        "duration_weeks": 2,
                        "start_week": AS_OF + 2,
                        "target_segment": "All customers",
                    }
                ]
            },
        )

    assert isinstance(result, ToolOk)
    assert isinstance(result.output, EstimateDemandOutput)
    assert result.output.model.model_id == latest.model_id
    assert result.output.model.version == 2
    assert result.output.estimates[0].units > 0
