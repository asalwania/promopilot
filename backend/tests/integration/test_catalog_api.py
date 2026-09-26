"""The catalogue and inventory endpoints against real Postgres, as `build_app` wires them (#68)."""

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from testcontainers.community.postgres import PostgresContainer

from promopilot.agents.tools import ToolOk, ToolRegistry
from promopilot.api.main import build_app
from promopilot.data import load_dataset
from promopilot.datagen import GeneratedDataset, write

pytestmark = pytest.mark.integration

HISTORY_WEEKS = 52  # small_config: the default as-of week


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


@pytest.fixture
def app_env(postgres_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", postgres_url)
    monkeypatch.setenv("MODEL_DIR", str(tmp_path))


@pytest.mark.usefixtures("app_env")
async def test_the_catalogue_endpoints_list_every_product_and_store(
    small_dataset: GeneratedDataset,
) -> None:
    app = build_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        products = await client.get("/api/catalog/products")
        regions = await client.get("/api/catalog/regions")

    assert products.status_code == 200
    assert [p["sku_id"] for p in products.json()["products"]] == sorted(
        small_dataset.products["sku_id"]
    )
    assert regions.status_code == 200
    stores = {
        store["store_id"]: (region["region"], store["segment_mix"])
        for region in regions.json()["regions"]
        for store in region["stores"]
    }
    assert set(stores) == set(small_dataset.stores["store_id"])
    for region, mix in stores.values():
        assert region in set(small_dataset.stores["region"])
        assert sum(mix.values()) == pytest.approx(1.0)


@pytest.mark.usefixtures("app_env")
async def test_the_inventory_endpoint_matches_the_planners_tool_with_names() -> None:
    app = build_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        response = await client.get("/api/inventory", params={"region": "South"})
        tools = app.state.tools
        assert isinstance(tools, ToolRegistry)
        tool = await tools.call("get_inventory_status", {"regions": ["South"]})

    assert response.status_code == 200
    assert isinstance(tool, ToolOk)
    body = response.json()
    assert body["as_of_week"] == HISTORY_WEEKS
    assert [
        {key: row[key] for key in row if key not in ("name", "category")}
        for row in body["statuses"]
    ] == tool.output.model_dump(mode="json")["statuses"]
    assert all(row["name"] and row["category"] for row in body["statuses"])
