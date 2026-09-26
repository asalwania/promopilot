"""The committed cassettes answer every committed brief, so CI and the demo need no API key."""

import json
from pathlib import Path

import pytest

from promopilot.agents import plan_session
from promopilot.datagen import GeneratedDataset
from promopilot.llm import ReplayProvider
from tests.unit.agents.fakes import InMemoryRetailData

CASSETTE_DIR = Path(__file__).parents[3] / "cassettes"
BRIEFS = json.loads((CASSETTE_DIR / "briefs.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("brief", BRIEFS)
async def test_a_committed_brief_replays_to_a_plan_over_the_default_world(
    brief: str, default_dataset: GeneratedDataset
) -> None:
    # A miss here means a prompt, schema or the default world changed: `make record-cassettes`.
    result = await plan_session(
        brief, ReplayProvider(CASSETTE_DIR), InMemoryRetailData(default_dataset)
    )

    assert result.revision.number == 1
    assert len(result.revision.lines) > 0
