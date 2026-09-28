"""The committed cassettes are the recording of every committed session script, so CI and the
demo need no API key (ADR 0022, ADR 0054).

These checks need no trained model: the manifest lists what each session called, and every
Context reading a session makes replays over the default world. A miss here means a prompt, a
schema, the calendar or a script changed: `make record-cassettes`. The images job replays the
whole sessions on the composed stack (`python -m promopilot.cassettes --check`).
"""

from pathlib import Path

import pytest

from promopilot.agents import (
    MAX_ATTEMPTS,
    SessionScript,
    load_scripts,
    manifest_problems,
    read_context,
    read_manifest,
)
from promopilot.datagen import GeneratedDataset
from promopilot.domain import Clarification, CompanyPolicy
from promopilot.llm import ReplayProvider
from tests.unit.agents.fakes import InMemoryRetailData

CASSETTE_DIR = Path(__file__).parents[3] / "cassettes"
SCRIPTS = load_scripts(CASSETTE_DIR / "sessions.json")


def test_the_manifest_lists_every_session_as_scripted_and_every_cassette_it_called() -> None:
    assert manifest_problems(SCRIPTS, CASSETTE_DIR) == []


def test_every_recorded_planning_round_converges_or_stops_early() -> None:
    # A round whose findings repeat hands its best plan on (ADR 0059): none runs the planner
    # to the Critic's cap on attempts that plan the same.
    manifest = read_manifest(CASSETTE_DIR)
    assert manifest is not None
    for name, session in manifest.sessions.items():
        rounds = " ".join(session.route).split("explainer")
        attempts = [planning.split().count("planner") for planning in rounds]
        assert max(attempts) < MAX_ATTEMPTS, f"{name}: {attempts} planner attempts per round"


def test_the_demo_the_e2e_journey_and_a_clarification_are_scripted() -> None:
    assert {"demo", "e2e", "clarify"} <= {script.name for script in SCRIPTS}
    assert any(step.answers for script in SCRIPTS for step in script.steps)
    assert any(step.amend for script in SCRIPTS for step in script.steps)


@pytest.mark.parametrize("script", SCRIPTS, ids=[script.name for script in SCRIPTS])
async def test_every_context_reading_of_a_session_replays_over_the_default_world(
    script: SessionScript, default_dataset: GeneratedDataset
) -> None:
    # As the graph reads it: the brief, then again after each answer or amendment (ADR 0048,
    # ADR 0052). A miss raises, as the reading is strict here (ADR 0053).
    replay, data, policy = (
        ReplayProvider(CASSETTE_DIR),
        InMemoryRetailData(default_dataset),
        CompanyPolicy(),
    )
    clarifications: tuple[Clarification, ...] = ()
    amendments: tuple[str, ...] = ()
    reading = await read_context(script.brief, replay, data, policy=policy)
    for step in script.steps:
        if step.approve:
            continue
        if step.answers is not None:
            assert {q.id for q in reading.questions} == set(step.answers)
            clarifications += tuple(
                Clarification(question=q, answer=step.answers[q.id]) for q in reading.questions
            )
        else:
            assert reading.request is not None
            amendments += (step.amend or "",)
        reading = await read_context(
            script.brief,
            replay,
            data,
            policy=policy,
            clarifications=clarifications,
            amendments=amendments,
        )

    assert reading.questions == ()
    assert reading.request is not None
    assert reading.request.marketing_budget > 0
