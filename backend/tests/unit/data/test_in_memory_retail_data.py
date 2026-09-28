"""The in-memory retail data reads a generated dataset's tables as Postgres would, as of a week
(ADR 0008, ADR 0056)."""

import pytest

from promopilot.data import InMemoryRetailData
from promopilot.datagen import GeneratedDataset


async def test_it_reads_at_the_week_after_the_history_by_default(
    small_dataset: GeneratedDataset,
) -> None:
    data = InMemoryRetailData(small_dataset)

    assert await data.default_as_of_week() == 52


async def test_a_fixed_as_of_week_is_the_clock_and_hides_the_future(
    small_dataset: GeneratedDataset,
) -> None:
    data = InMemoryRetailData(small_dataset, as_of_week=30)

    assert await data.default_as_of_week() == 30
    snapshot = await data.inventory(30)
    assert set(snapshot["snapshot_week"]) == {29}
    assert (await data.sales_history(30))["week_id"].max() == 29
    latest = await data.latest_competitor_prices(30)
    assert latest["week_id"].max() == 29
    assert not latest.duplicated(["region", "sku_id"]).any()


async def test_an_as_of_week_with_no_snapshot_is_a_lookup_error(
    small_dataset: GeneratedDataset,
) -> None:
    with pytest.raises(LookupError, match="no inventory snapshot"):
        await InMemoryRetailData(small_dataset).inventory(500)
