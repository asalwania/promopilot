"""Whether a replayed session stays on the demo recordings (ADR 0073): the brief, answers and
amendments so far must be those of a recorded session script, or it plans without the LLM."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from promopilot.agents import (
    CassetteManifest,
    RecordedSession,
    ScriptStep,
    SessionScript,
    load_scripts,
)
from promopilot.api.demo import DemoRecording, DemoRecordings
from promopilot.domain import (
    Amendment,
    Clarification,
    ClarificationQuestion,
    PlanningSession,
    QuestionReason,
    SessionStatus,
)

BRIEF = "Plan Diwali promotions for Snacks. Budget ₹8 lakh."
VAGUE = "Plan Diwali promotions for Snacks."
ACCEPTED = "Accept the smallest relaxation: lower the clearance target for SKU0006 to 59.86%."


def recorded(script: SessionScript, amendments: tuple[str, ...] = ()) -> RecordedSession:
    return RecordedSession(
        script=script, route=("context",), cassettes=(), revisions=(), amendments=amendments
    )


MANIFEST = CassetteManifest(
    planning_settings={},
    sessions={
        "demo": recorded(
            SessionScript(
                name="demo",
                brief=BRIEF,
                steps=(
                    ScriptStep(amend="Budget cut to ₹6 lakh"),
                    ScriptStep(accept_relaxation=True),
                    ScriptStep(approve=True),
                ),
            ),
            amendments=("Budget cut to ₹6 lakh", ACCEPTED),
        ),
        "clarify": recorded(
            SessionScript(
                name="clarify",
                brief=VAGUE,
                steps=(ScriptStep(answers={"marketing_budget": "₹2 lakh"}),),
            )
        ),
    },
)


def session(
    brief: str, *, answers: dict[str, str] | None = None, amendments: tuple[str, ...] = ()
) -> PlanningSession:
    return PlanningSession(
        id=uuid4(),
        brief=brief,
        status=SessionStatus.AWAITING_APPROVAL,
        clarifications=tuple(
            Clarification(
                question=ClarificationQuestion(
                    id=question_id,
                    field=question_id,
                    question="How much?",
                    reason=QuestionReason.MISSING,
                ),
                answer=answer,
            )
            for question_id, answer in (answers or {}).items()
        ),
        amendments=tuple(
            Amendment(text=text, amends_revision=number, amended_at=datetime.now(UTC))
            for number, text in enumerate(amendments, start=1)
        ),
    )


def test_a_recorded_brief_is_recorded() -> None:
    assert DemoRecordings(MANIFEST).of(session(BRIEF)) is DemoRecording.RECORDED


def test_any_other_brief_is_not_in_the_demo_recordings() -> None:
    recordings = DemoRecordings(MANIFEST)

    assert recordings.of(session(BRIEF + " Target families.")) is DemoRecording.NOT_RECORDED
    assert recordings.of(session("Plan something")) is DemoRecording.NOT_RECORDED


def test_the_recorded_amendments_in_order_stay_recorded() -> None:
    recordings = DemoRecordings(MANIFEST)

    assert recordings.of(session(BRIEF, amendments=("Budget cut to ₹6 lakh",))) is (
        DemoRecording.RECORDED
    )
    assert recordings.of(session(BRIEF, amendments=("Budget cut to ₹6 lakh", ACCEPTED))) is (
        DemoRecording.RECORDED
    )


def test_an_amendment_the_script_does_not_make_leaves_the_recordings() -> None:
    recordings = DemoRecordings(MANIFEST)

    assert recordings.of(session(BRIEF, amendments=("Drop West",))) is DemoRecording.NOT_RECORDED
    assert recordings.of(session(BRIEF, amendments=(ACCEPTED,))) is DemoRecording.NOT_RECORDED
    assert recordings.of(session(VAGUE, amendments=("Budget cut to ₹6 lakh",))) is (
        DemoRecording.NOT_RECORDED
    )


def test_the_recorded_answer_stays_recorded_and_another_leaves() -> None:
    recordings = DemoRecordings(MANIFEST)

    assert recordings.of(session(VAGUE, answers={"marketing_budget": "₹2 lakh"})) is (
        DemoRecording.RECORDED
    )
    assert recordings.of(session(VAGUE, answers={"marketing_budget": "₹3 lakh"})) is (
        DemoRecording.NOT_RECORDED
    )
    assert recordings.of(session(BRIEF, answers={"marketing_budget": "₹2 lakh"})) is (
        DemoRecording.NOT_RECORDED
    )


def test_without_a_manifest_nothing_is_recorded(tmp_path: Path) -> None:
    recordings = DemoRecordings.read(tmp_path)

    assert recordings.of(session(BRIEF)) is DemoRecording.NOT_RECORDED


def test_the_committed_recordings_hold_every_session_script() -> None:
    recordings = DemoRecordings.read(Path("cassettes"))

    assert recordings.of(session(BRIEF)) is DemoRecording.NOT_RECORDED
    assert recordings.briefs() == frozenset(
        script.brief for script in load_scripts(Path("cassettes/sessions.json"))
    )
