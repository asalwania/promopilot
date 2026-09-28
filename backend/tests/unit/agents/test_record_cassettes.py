from pathlib import Path

import pytest

from promopilot.agents import (
    AgentTools,
    BriefReading,
    RecordedPlanning,
    RecordingError,
    plan_with_tools,
    read_planning_request,
    record_cassettes,
)
from promopilot.datagen import GeneratedDataset
from promopilot.domain import Region
from promopilot.llm import FakeProvider, ReplayProvider, cassette_paths
from tests.unit.agents.fakes import InMemoryRetailData
from tests.unit.agents.test_graph import ScriptedPlanner, planned
from tests.unit.agents.test_planner_agent import (
    SET_ID,
    Generated,
    Revisions,
    ScriptedTools,
    finish,
    generate,
    optimised,
    run,
)

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


async def test_recorded_briefs_replay_to_the_same_planning_request_with_no_live_provider(
    data: InMemoryRetailData, tmp_path: Path
) -> None:
    recorded = await record_cassettes([BRIEF], FakeProvider([reading()]), data, tmp_path)

    replayed = await read_planning_request(BRIEF, ReplayProvider(tmp_path), data)

    assert replayed == recorded[0]
    assert replayed.marketing_budget == 20_000.0


async def test_a_brief_that_does_not_read_fails_the_run_and_keeps_the_old_cassettes(
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


# With the planner agent (ADR 0049): its tool-calling turns are recorded too, so a session
# replays them with no key; recording needs trained models and fails rather than degrade.


def agent_tools() -> AgentTools:
    tools = ScriptedTools(
        {
            "generate_candidates": [Generated(candidate_set_id=SET_ID)],
            "run_optimizer": [optimised()],
        }
    )
    return AgentTools(tools=tools, revisions=Revisions({SET_ID: planned()}))


async def test_the_planner_agents_turns_are_recorded_and_replay_to_the_same_plan(
    data: InMemoryRetailData, tmp_path: Path
) -> None:
    request = await read_planning_request(BRIEF, FakeProvider([reading()]), data)
    live = FakeProvider([reading(), generate(request), run(), finish()])
    fallback = ScriptedPlanner(planned(promo_cost=900.0))

    await record_cassettes(
        [BRIEF], live, data, tmp_path, planning=RecordedPlanning(agent_tools(), fallback)
    )

    assert len(cassette_paths(tmp_path)) == 4, "the reading and three planner steps"
    replay = ReplayProvider(tmp_path)
    replayed = await plan_with_tools(
        BRIEF, await read_planning_request(BRIEF, replay, data), replay, agent_tools(), fallback
    )
    assert replayed.degraded is None
    assert replayed.revision == planned().revision
    assert fallback.requests == []


async def test_a_brief_the_planner_agent_cannot_plan_fails_the_run(
    data: InMemoryRetailData, tmp_path: Path
) -> None:
    live = FakeProvider([reading(), finish("No plan."), finish("Still none.")])
    fallback = ScriptedPlanner(planned(promo_cost=900.0))

    with pytest.raises(RecordingError, match="no_optimised_plan"):
        await record_cassettes(
            [BRIEF], live, data, tmp_path, planning=RecordedPlanning(agent_tools(), fallback)
        )

    assert names(tmp_path) == set()
