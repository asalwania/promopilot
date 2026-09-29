"""Whether a replayed session stays on the demo recordings (ADR 0073).

With no API key the stack replays the committed cassettes (ADR 0022, ADR 0054). A session
whose brief, answers and amendments so far are those of a recorded session script replays as
recorded. Any other session still plans, without the LLM: the Context agent reads by rules, the
planner runs the default sequence and the Explainer uses its template (ADR 0049, 0050, 0053).
The read model says which, so the UI can explain the demo's limits instead of an error.
"""

from enum import StrEnum
from pathlib import Path

from promopilot.agents import CassetteManifest, RecordedSession, read_manifest
from promopilot.domain import PlanningSession


class DemoRecording(StrEnum):
    RECORDED = "recorded"
    """Everything the session was given so far is in a recorded session: it replays."""
    NOT_RECORDED = "not_in_demo_recordings"
    """Something it was given is not: it plans without the language model."""


class DemoRecordings:
    """The recorded session scripts of the cassette manifest."""

    def __init__(self, manifest: CassetteManifest | None) -> None:
        self._sessions = tuple(manifest.sessions.values()) if manifest is not None else ()

    @classmethod
    def read(cls, cassette_dir: Path) -> "DemoRecordings":
        return cls(read_manifest(cassette_dir))

    def briefs(self) -> frozenset[str]:
        return frozenset(recorded.script.brief for recorded in self._sessions)

    def of(self, session: PlanningSession) -> DemoRecording:
        if any(_follows(recorded, session) for recorded in self._sessions):
            return DemoRecording.RECORDED
        return DemoRecording.NOT_RECORDED


def _follows(recorded: RecordedSession, session: PlanningSession) -> bool:
    script = recorded.script
    if session.brief != script.brief:
        return False
    answers = {
        (question_id, answer)
        for step in script.steps
        for question_id, answer in (step.answers or {}).items()
    }
    given = {(done.question.id, done.answer) for done in session.clarifications}
    # The texts of accepted relaxations come from the plan, so the manifest keeps them; an
    # older entry without them has only the scripted amendments (ADR 0070 D5).
    amendments = recorded.amendments or tuple(
        step.amend for step in script.steps if step.amend is not None
    )
    made = tuple(amendment.text for amendment in session.amendments)
    return given <= answers and made == amendments[: len(made)]
