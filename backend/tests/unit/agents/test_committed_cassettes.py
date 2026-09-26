"""The committed cassettes answer every committed brief, so CI and the demo need no API key."""

import json
from pathlib import Path

import pytest

from promopilot.agents import read_planning_request
from promopilot.datagen import GeneratedDataset
from promopilot.llm import ReplayProvider
from tests.unit.agents.fakes import InMemoryRetailData

CASSETTE_DIR = Path(__file__).parents[3] / "cassettes"
BRIEFS = json.loads((CASSETTE_DIR / "briefs.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("brief", BRIEFS)
async def test_a_committed_brief_replays_to_a_planning_request_over_the_default_world(
    brief: str, default_dataset: GeneratedDataset
) -> None:
    # A miss here means a prompt, schema or the default world changed: `make record-cassettes`.
    # Planning after the reading calls no LLM (ADR 0038).
    request = await read_planning_request(
        brief, ReplayProvider(CASSETTE_DIR), InMemoryRetailData(default_dataset)
    )

    assert request.scope.regions
    assert request.marketing_budget > 0
