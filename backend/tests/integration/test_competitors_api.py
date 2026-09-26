"""Competitor gaps against real Postgres, as `build_app` wires them (#32, ADR 0031)."""

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from testcontainers.community.postgres import PostgresContainer

from promopilot.agents.tools import ToolOk, ToolRegistry
from promopilot.api.main import build_app
from promopilot.competitors import CompetitorGaps
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


def expected_gaps(dataset: GeneratedDataset, as_of_week: int) -> dict[tuple[str, str], float]:
    """The competitor's price in the week before, over our base price, for every SKU x region."""
    prices = dataset.competitor_prices
    week = prices[prices["week_id"] == as_of_week - 1].merge(dataset.products, on="sku_id")
    index = week["competitor_price"] / week["base_price"]
    return {
        (str(region), str(sku_id)): 1 - float(cpi)
        for region, sku_id, cpi in zip(week["region"], week["sku_id"], index, strict=True)
    }


@pytest.mark.usefixtures("app_env")
async def test_the_tool_reads_gaps_at_the_default_as_of_week(
    small_dataset: GeneratedDataset,
) -> None:
    app = build_app()
    async with app.router.lifespan_context(app):
        tools = app.state.tools
        assert isinstance(tools, ToolRegistry)
        result = await tools.call("get_competitor_gaps", {})

    assert isinstance(result, ToolOk)
    assert isinstance(result.output, CompetitorGaps)
    assert result.output.as_of_week == HISTORY_WEEKS
    expected = expected_gaps(small_dataset, HISTORY_WEEKS)
    assert {(g.region.value, g.sku_id): g.gap for g in result.output.gaps} == pytest.approx(
        expected
    )
    kvis = small_dataset.products.set_index("sku_id")["is_kvi"]
    undercut = {(g.region.value, g.sku_id) for g in result.output.gaps if g.undercut}
    assert undercut == {key for key, gap in expected.items() if kvis[key[1]] and gap > 0.05}


@pytest.mark.usefixtures("app_env")
async def test_the_endpoint_filters_and_takes_an_earlier_as_of_week(
    small_dataset: GeneratedDataset,
) -> None:
    app = build_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        response = await client.get(
            "/api/competitors/gaps", params={"region": "South", "kvi_only": True, "as_of_week": 30}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["as_of_week"] == 30
    kvis = set(small_dataset.products.loc[small_dataset.products["is_kvi"], "sku_id"])
    assert {g["sku_id"] for g in body["gaps"]} == kvis
    assert {(g["region"], g["price_week"]) for g in body["gaps"]} == {("South", 29)}
