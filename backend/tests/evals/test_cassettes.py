"""The eval's cassettes (#56, ADR 0065): replay reads the eval's own folder, then the app's, and
recording writes only what neither holds into the eval's folder. No real LLM is called."""

from pathlib import Path

import pytest
from pydantic import BaseModel

from promopilot.evals.cassettes import LiveUsage, recording_provider, replay_provider
from promopilot.llm import (
    CassetteMissError,
    FakeProvider,
    Message,
    RecordingProvider,
    ToolSpec,
    ToolTurn,
    Usage,
)
from tests.unit.agents.billed import BilledProvider


class Answer(BaseModel):
    text: str


ASKED = [Message(role="user", content="What is on promotion?")]
OTHER = [Message(role="user", content="Something else")]
TOOLS = [ToolSpec(name="lookup", description="Look it up", input_schema={"type": "object"})]


async def record(folder: Path, answer: str, messages: list[Message] = ASKED) -> None:
    """A cassette for `messages` answered with `answer`, as a live recording writes it."""
    await RecordingProvider(FakeProvider([Answer(text=answer)]), folder).complete_structured(
        Answer, messages
    )


@pytest.fixture
def folders(tmp_path: Path) -> tuple[Path, Path]:
    eval_dir, app_dir = tmp_path / "evals", tmp_path / "app"
    eval_dir.mkdir()
    app_dir.mkdir()
    return eval_dir, app_dir


async def test_replay_reads_the_eval_folder_first_then_the_apps(
    folders: tuple[Path, Path],
) -> None:
    eval_dir, app_dir = folders
    await record(eval_dir, "from the eval")
    await record(app_dir, "from the app")
    await record(app_dir, "only the app", OTHER)

    replay = replay_provider(eval_dir, app_dir)

    assert (await replay.complete_structured(Answer, ASKED)).text == "from the eval"
    assert (await replay.complete_structured(Answer, OTHER)).text == "only the app"


async def test_replay_misses_when_neither_folder_holds_the_request(
    folders: tuple[Path, Path],
) -> None:
    replay = replay_provider(*folders)

    with pytest.raises(CassetteMissError):
        await replay.complete_structured(Answer, ASKED)
    with pytest.raises(CassetteMissError):
        await replay.complete_with_tools(TOOLS, ASKED)


async def test_recording_asks_the_live_model_only_what_no_cassette_holds_and_keeps_it(
    folders: tuple[Path, Path],
) -> None:
    eval_dir, app_dir = folders
    await record(app_dir, "from the app")
    app_cassettes = sorted(app_dir.iterdir())
    live = FakeProvider([Answer(text="live"), ToolTurn(text="live tools")])

    recorder = recording_provider(live, eval_dir, app_dir)

    assert (await recorder.complete_structured(Answer, ASKED)).text == "from the app"
    assert (await recorder.complete_structured(Answer, OTHER)).text == "live"
    assert (await recorder.complete_with_tools(TOOLS, OTHER)).text == "live tools"
    assert len(live.calls) == 2, "the app's cassette answered without a live call"
    assert len(list(eval_dir.iterdir())) == 2, "only the live answers are written"
    assert sorted(app_dir.iterdir()) == app_cassettes, "the app's cassettes are untouched"
    replayed = replay_provider(eval_dir, app_dir)
    assert (await replayed.complete_structured(Answer, OTHER)).text == "live"
    assert (await replayed.complete_with_tools(TOOLS, OTHER)).text == "live tools"


async def test_a_second_recording_answers_from_the_first_without_asking_again(
    folders: tuple[Path, Path],
) -> None:
    eval_dir, app_dir = folders
    await record(eval_dir, "recorded before")
    live = FakeProvider([])

    recorder = recording_provider(live, eval_dir, app_dir)

    assert (await recorder.complete_structured(Answer, ASKED)).text == "recorded before"
    assert live.calls == []


async def test_a_recording_counts_what_the_live_calls_were_billed_and_not_the_replays(
    folders: tuple[Path, Path],
) -> None:
    eval_dir, app_dir = folders
    await record(app_dir, "from the app")
    billed = Usage(model="gpt-4.1-mini", input_tokens=1_000, output_tokens=100)
    live = LiveUsage(BilledProvider(FakeProvider([Answer(text="live")]), [billed]))

    recorder = recording_provider(live, eval_dir, app_dir)
    await recorder.complete_structured(Answer, ASKED)
    await recorder.complete_structured(Answer, OTHER)

    assert live.meter.usages == (billed,)
