from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from promopilot.data import RetailData, load_dataset
from promopilot.datagen import GeneratedDataset, write
from promopilot.domain import Region

pytestmark = pytest.mark.integration

AS_OF = 30


@pytest.fixture(scope="module")
def postgres_url() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as postgres:
        yield postgres.get_connection_url()


@pytest.fixture(scope="module")
def data_dir(small_dataset: GeneratedDataset, tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("data")
    write(small_dataset, out)
    return out


@pytest.fixture
async def engine(postgres_url: str, data_dir: Path) -> AsyncIterator[AsyncEngine]:
    await load_dataset(data_dir, postgres_url)
    engine = create_async_engine(postgres_url)
    yield engine
    await engine.dispose()


async def test_loaded_tables_read_back_through_the_repositories(
    engine: AsyncEngine, small_dataset: GeneratedDataset
) -> None:
    data = RetailData(engine)

    products = await data.products()
    stores = await data.stores()
    calendar = await data.calendar()

    assert list(products["sku_id"]) == list(small_dataset.products["sku_id"])
    assert products["base_price"].tolist() == small_dataset.products["base_price"].tolist()
    assert len(stores) == len(small_dataset.stores)
    assert stores["segment_mix"].map(lambda mix: set(mix)).iloc[0] == {
        "Value Seekers",
        "Families",
        "Premium",
        "Young Urban",
    }
    assert len(calendar) == len(small_dataset.calendar)


async def test_history_is_hidden_at_and_after_the_as_of_week(
    engine: AsyncEngine, small_dataset: GeneratedDataset
) -> None:
    data = RetailData(engine)

    sales = await data.sales_history(AS_OF)
    promotions = await data.promotions_history(AS_OF)
    competitors = await data.competitor_prices(AS_OF)
    baskets = await data.baskets(AS_OF)

    assert sales["week_id"].max() == AS_OF - 1
    assert len(sales) == (small_dataset.sales_weekly["week_id"] < AS_OF).sum()
    assert (promotions["start_week"] + promotions["duration"] <= AS_OF).all()
    assert competitors["week_id"].max() == AS_OF - 1
    assert baskets["week_id"].max() < AS_OF
    assert isinstance(baskets["sku_ids"].iloc[0], list)


async def test_a_promotion_running_across_the_as_of_week_is_cut_at_it(
    engine: AsyncEngine, small_dataset: GeneratedDataset
) -> None:
    promos = small_dataset.promotions_history
    spanning = promos[
        (promos["start_week"] < AS_OF) & (promos["start_week"] + promos["duration"] > AS_OF)
    ]
    assert len(spanning) > 0

    visible = (await RetailData(engine).promotions_history(AS_OF)).set_index("promo_id")

    for promo_id, start in zip(spanning["promo_id"], spanning["start_week"], strict=True):
        assert visible.loc[promo_id, "duration"] == AS_OF - start


async def test_inventory_for_an_as_of_week_is_the_snapshot_at_the_end_of_the_week_before(
    engine: AsyncEngine, small_dataset: GeneratedDataset
) -> None:
    inventory = await RetailData(engine).inventory(AS_OF, region=Region.SOUTH)

    assert set(inventory["snapshot_week"]) == {AS_OF - 1}
    south = small_dataset.stores.loc[small_dataset.stores["region"] == "South", "store_id"]
    assert set(inventory["store_id"]) == set(south)
    assert len(inventory) == len(south) * len(small_dataset.products)


async def test_latest_competitor_prices_are_the_last_week_before_the_as_of_week(
    engine: AsyncEngine, small_dataset: GeneratedDataset
) -> None:
    latest = await RetailData(engine).latest_competitor_prices(AS_OF)

    history = small_dataset.competitor_prices
    expected = history[history["week_id"] == AS_OF - 1]
    assert len(latest) == len(expected) == len(small_dataset.products) * 2
    assert set(latest["week_id"]) == {AS_OF - 1}
    merged = latest.merge(expected, on=["region", "sku_id"], suffixes=("", "_expected"))
    assert (merged["competitor_price"] == merged["competitor_price_expected"]).all()
    assert (merged["competitor_on_promo"] == merged["competitor_on_promo_expected"]).all()
    assert (await RetailData(engine).latest_competitor_prices(0)).empty


async def test_queries_narrow_by_region_and_sku(
    engine: AsyncEngine, small_dataset: GeneratedDataset
) -> None:
    data = RetailData(engine)
    sku_ids = list(small_dataset.products["sku_id"][:2])

    sales = await data.sales_history(AS_OF, region=Region.NORTH, sku_ids=sku_ids, since_week=20)
    competitors = await data.competitor_prices(AS_OF, region=Region.NORTH, sku_ids=sku_ids)

    north = set(small_dataset.stores.loc[small_dataset.stores["region"] == "North", "store_id"])
    assert set(sales["store_id"]) == north
    assert set(sales["sku_id"]) == set(sku_ids)
    assert sales["week_id"].min() == 20
    assert set(competitors["region"]) == {"North"}


async def test_reloading_the_same_dataset_never_duplicates_rows(
    engine: AsyncEngine, postgres_url: str, data_dir: Path, small_dataset: GeneratedDataset
) -> None:
    await load_dataset(data_dir, postgres_url)
    await load_dataset(data_dir, postgres_url)

    sales = await RetailData(engine).sales_history(small_dataset.config.history_weeks)
    assert len(sales) == len(small_dataset.sales_weekly)


async def test_an_as_of_week_without_an_inventory_snapshot_is_rejected(engine: AsyncEngine) -> None:
    with pytest.raises(LookupError, match="snapshot"):
        await RetailData(engine).inventory(0)


async def test_the_datagen_cli_generates_writes_and_loads(
    postgres_url: str, tmp_path: Path
) -> None:
    from promopilot.datagen.__main__ import run

    config = tmp_path / "tiny.yaml"
    config.write_text(
        "catalogue: {categories_limit: 2, skus_per_category: 4}\n"
        "regions: [East]\nstores_per_region: 2\nhistory_weeks: 12\nhorizon_weeks: 4\n"
        "baskets: 50\ncomplement_pairs: 2\n",
        encoding="utf-8",
    )

    await run(
        ["--config", str(config), "--out", str(tmp_path), "--load", "--database-url", postgres_url]
    )

    engine = create_async_engine(postgres_url)
    try:
        assert len(await RetailData(engine).products()) == 8
    finally:
        await engine.dispose()
