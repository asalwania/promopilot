"""Every number the LLM wrote in a recorded session comes from a tool (SPEC §13.4, ADR 0054).

The cassettes are the recorded sessions: each Explainer and Critic request carries the tool
data the answer was checked against, so numeric grounding runs over every shown answer without
replaying anything. And no recorded session fell back to the template (ADR 0050 D7).
"""

import json
from pathlib import Path

from promopilot.agents import ExplainerAnswer, read_manifest, ungrounded_answers
from promopilot.domain import ExplanationSource
from promopilot.llm import cassette_paths

CASSETTE_DIR = Path(__file__).parents[2] / "cassettes"


def test_every_number_in_a_recorded_explanation_or_critique_is_in_its_tool_data() -> None:
    cassettes = cassette_paths(CASSETTE_DIR)
    explained = [
        path
        for path in cassettes
        if json.loads(path.read_text(encoding="utf-8"))["schema_name"] == ExplainerAnswer.__name__
    ]
    assert explained, "no recorded explanation: `make record-cassettes`"

    assert ungrounded_answers(cassettes) == []


def test_every_recorded_plan_revision_was_explained_by_the_llm() -> None:
    manifest = read_manifest(CASSETTE_DIR)
    assert manifest is not None, "no manifest: `make record-cassettes`"
    for name, session in manifest.sessions.items():
        assert session.revisions, f"session {name!r} planned nothing"
        assert {revision.explanation for revision in session.revisions} == {ExplanationSource.LLM}
