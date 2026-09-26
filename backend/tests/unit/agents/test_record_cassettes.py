from pathlib import Path

import pytest

from promopilot.agents import BriefReading, RecordingError, plan_session, record_cassettes
from promopilot.datagen import GeneratedDataset
from promopilot.domain import Region
from promopilot.llm import FakeProvider, ReplayProvider
from tests.unit.agents.fakes import InMemoryRetailData

HISTORY_WEEKS = 52  # small_config
BRIEF = "Snacks push in the North, ₹20k, weeks 54-55"


@pytest.fixture
def data(small_dataset: GeneratedDataset) -> InMemoryRetailData:
    return InMemoryRetailData(small_dataset)


def reading() -> BriefReading:
    return BriefReading(
        regions=[Region.NORTH],
        categories=["Snacks"],
        sku_ids=None,
        promo_start_week=HISTORY_WEEKS + 2,
        promo_end_week=HISTORY_WEEKS + 3,
        marketing_budget=20_000.0,
        min_margin=None,
    )


def names(directory: Path) -> set[str]:
    return {path.name for path in directory.iterdir()}


async def test_recorded_briefs_replay_to_the_same_plan_with_no_live_provider(
    data: InMemoryRetailData, tmp_path: Path
) -> None:
    recorded = await record_cassettes([BRIEF], FakeProvider([reading()]), data, tmp_path)

    replayed = await plan_session(BRIEF, ReplayProvider(tmp_path), data)

    assert replayed == recorded[0]
    assert len(replayed.revision.lines) > 0


async def test_a_brief_that_does_not_plan_fails_the_run_and_keeps_the_old_cassettes(
    data: InMemoryRetailData, tmp_path: Path
) -> None:
    old = tmp_path / f"{'a' * 64}.json"
    old.write_text("{}", encoding="utf-8")
    no_budget = reading().model_copy(update={"marketing_budget": None})
    live = FakeProvider([reading(), no_budget])

    with pytest.raises(RecordingError, match="vague brief"):
        await record_cassettes([BRIEF, "vague brief"], live, data, tmp_path)

    assert names(tmp_path) == {old.name}


async def test_a_full_run_replaces_stale_cassettes_and_keeps_other_files(
    data: InMemoryRetailData, tmp_path: Path
) -> None:
    stale = tmp_path / f"{'a' * 64}.json"
    stale.write_text("{}", encoding="utf-8")
    briefs = tmp_path / "briefs.json"
    briefs.write_text(f'["{BRIEF}"]', encoding="utf-8")

    await record_cassettes([BRIEF], FakeProvider([reading()]), data, tmp_path)

    names_after = names(tmp_path)
    assert stale.name not in names_after
    assert briefs.name in names_after
    assert len(names_after) == 2, "one fresh cassette next to briefs.json"
