"""The API builds its tools over Postgres: the latest models and the as-of-week data."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.community.postgres import PostgresContainer

from promopilot.agents.tools import ToolError, ToolOk, ToolRegistry
from promopilot.agents.tools.estimate_demand import EstimateDemandOutput
from promopilot.agents.tools.get_relations import GetRelationsOutput
from promopilot.agents.tools.holidays import GetHolidaysOutput
from promopilot.agents.tools.inventory_status import GetInventoryStatusOutput
from promopilot.agents.tools.scope_data import GetScopeDataOutput
from promopilot.api.main import build_app
from promopilot.data import load_dataset, migrate
from promopilot.datagen import GeneratedDataset, write
from promopilot.models import demand
from promopilot.models.demand import DemandHistory, DemandModel
from promopilot.models.registry import ModelKind, ModelRegistry
from promopilot.models.relations import Relations

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


async def test_the_api_serves_the_data_tools_at_the_loaded_datas_as_of_week(
    postgres_url: str,
    tmp_path: Path,
    small_dataset: GeneratedDataset,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write(small_dataset, tmp_path / "data")
    await load_dataset(tmp_path / "data", postgres_url)
    monkeypatch.setenv("DATABASE_URL", postgres_url)
    monkeypatch.setenv("MODEL_DIR", str(tmp_path / "models"))
    as_of = int(small_dataset.sales_weekly["week_id"].max()) + 1
    sku_id = str(small_dataset.products["sku_id"].iloc[0])

    app = build_app()
    async with app.router.lifespan_context(app):
        tools = app.state.tools
        assert "generate_candidates" in {spec.name for spec in tools.specs()}
        scope = await tools.call("get_scope_data", {"regions": ["North"]})
        stock = await tools.call("get_inventory_status", {"sku_ids": [sku_id]})
        holidays = await tools.call(
            "get_holidays", {"start_week": as_of + 1, "end_week": as_of + 11}
        )

    assert isinstance(scope, ToolOk)

    assert isinstance(scope.output, GetScopeDataOutput)
    assert [r.region.value for r in scope.output.regions] == ["North"]
    assert isinstance(stock, ToolOk)
    assert isinstance(stock.output, GetInventoryStatusOutput)
    assert (stock.output.as_of_week, stock.output.snapshot_week) == (as_of, as_of - 1)
    snapshot = small_dataset.inventory[
        (small_dataset.inventory["snapshot_week"] == as_of - 1)
        & (small_dataset.inventory["sku_id"] == sku_id)
    ]
    assert sum(s.on_hand for s in stock.output.statuses) == snapshot["on_hand"].sum()
    assert isinstance(holidays, ToolOk)
    assert isinstance(holidays.output, GetHolidaysOutput)
    assert all(as_of < h.week_id <= as_of + 11 for h in holidays.output.holidays)


async def test_the_api_serves_get_relations_only_on_the_live_demand_model(
    postgres_url: str,
    tmp_path: Path,
    small_dataset: GeneratedDataset,
    small_models: tuple[DemandModel, Relations],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write(small_dataset, tmp_path / "data")
    await load_dataset(tmp_path / "data", postgres_url)
    model, relations = small_models
    engine = create_async_engine(postgres_url)
    try:
        await migrate(engine)
        async with engine.begin() as connection:
            await connection.exec_driver_sql("TRUNCATE model_registry")
        registry = ModelRegistry(engine, tmp_path)
        live_demand = await registry.register(ModelKind.DEMAND, model, as_of_week=AS_OF, metrics={})
        matched = await registry.register(
            ModelKind.RELATIONS,
            relations,
            as_of_week=AS_OF,
            metrics={"demand_version": float(live_demand.version)},
        )
    finally:
        await engine.dispose()
    monkeypatch.setenv("DATABASE_URL", postgres_url)
    monkeypatch.setenv("MODEL_DIR", str(tmp_path))
    sku_id = str(small_dataset.products["sku_id"].iloc[0])

    app = build_app()
    async with app.router.lifespan_context(app):
        result = await app.state.tools.call("get_relations", {"sku_ids": [sku_id]})

    assert isinstance(result, ToolOk)
    assert isinstance(result.output, GetRelationsOutput)
    assert result.output.model.model_id == matched.model_id
    assert [one.sku_id for one in result.output.relations] == [sku_id]

    # A newer demand version with no relations fitted on it: relations are not served.
    engine = create_async_engine(postgres_url)
    try:
        await ModelRegistry(engine, tmp_path).register(
            ModelKind.DEMAND, model, as_of_week=AS_OF, metrics={}
        )
    finally:
        await engine.dispose()
    app = build_app()
    async with app.router.lifespan_context(app):
        stale = await app.state.tools.call("get_relations", {"sku_ids": [sku_id]})

    assert isinstance(stale, ToolError)
    assert stale.code == "model_unavailable"
