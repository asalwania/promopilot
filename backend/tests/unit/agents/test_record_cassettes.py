"""`make record-cassettes` plays each session script through the full agent graph on a live
provider and records every LLM request, so CI and the demo replay whole sessions with no key
(ADR 0019, ADR 0022, ADR 0054). Here a FakeProvider stands in for the live provider, and the
planner agent's tools are scripted on the small world."""

import json
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import BaseModel, ValidationError

from promopilot.agents import (
    MANIFEST,
    AgentTools,
    BriefReading,
    CriticFeedback,
    ExplainerAnswer,
    FindingFeedback,
    LineRationale,
    PlannedRevision,
    RecordedPlanning,
    RecordingError,
    SessionScript,
    check_cassettes,
    load_scripts,
    manifest_problems,
    read_manifest,
    read_planning_request,
    record_cassettes,
    ungrounded_answers,
)
from promopilot.datagen import GeneratedDataset
from promopilot.domain import (
    BindingConstraint,
    BindingEvidence,
    ConstraintKind,
    ConstraintSource,
    ExplanationSource,
    PlanningRequest,
    Region,
    Relaxation,
    RelaxedConstraint,
    SolveStatus,
)
from promopilot.llm import (
    FakeProvider,
    LLMError,
    Message,
    RecordingProvider,
    ToolSpec,
    ToolTurn,
    cassette_paths,
)
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
VAGUE = "Snacks push in the North, weeks 54-55"
SETTINGS = {"optimizer_seed": 0, "simulation_runs": 1_000}

GROUNDED = ExplainerAnswer(
    summary="One Snacks line in North from W54, expected to add ₹6,250 for a ₹1,500 promo cost.",
    rationales=[
        LineRationale(line=1, rationale="SKU0001 at 20% off is expected to sell 400 units.")
    ],
)
UNGROUNDED = GROUNDED.model_copy(update={"summary": "One Snacks line, adding ₹7,000 in profit."})
CHANGED = GROUNDED.model_copy(update={"changes": "The same line stays within the lower budget."})


def reading(budget: float | None = 20_000.0) -> BriefReading:
    return BriefReading(
        regions=[Region.NORTH],
        categories=["Snacks"],
        sku_ids=None,
        promo_start_week=HISTORY_WEEKS + 2,
        promo_end_week=HISTORY_WEEKS + 3,
        marketing_budget=budget,
        min_margin=None,
    )


@pytest.fixture
def data(small_dataset: GeneratedDataset) -> InMemoryRetailData:
    return InMemoryRetailData(small_dataset)


async def request_for(data: InMemoryRetailData, budget: float = 20_000.0) -> PlanningRequest:
    return await read_planning_request(BRIEF, FakeProvider([reading(budget)]), data)


def planning(settings: dict[str, object] | None = None) -> RecordedPlanning:
    tools = ScriptedTools(
        {
            "generate_candidates": [Generated(candidate_set_id=SET_ID)],
            "run_optimizer": [optimised()],
        }
    )
    return RecordedPlanning(
        agent=AgentTools(tools=tools, revisions=Revisions({SET_ID: planned()})),
        default=ScriptedPlanner(planned(promo_cost=900.0)),
        settings=SETTINGS if settings is None else settings,
    )


def round_turns(request: PlanningRequest) -> list[BaseModel]:
    """The planner agent's steps for one planning round: generate, optimise, stop."""
    return [generate(request), run(), finish()]


def script(name: str = "plan", brief: str = BRIEF, *steps: dict[str, object]) -> SessionScript:
    return SessionScript.model_validate({"name": name, "brief": brief, "steps": steps})


def names(directory: Path) -> set[str]:
    return {path.name for path in directory.iterdir()}


# --- recording a session, then replaying it with no live provider ---------------------------


async def test_a_recorded_session_replays_through_the_whole_graph_with_no_live_provider(
    data: InMemoryRetailData, tmp_path: Path
) -> None:
    live = FakeProvider([reading(), *round_turns(await request_for(data)), GROUNDED])

    manifest = await record_cassettes([script()], live, data, tmp_path, planning())

    recorded = manifest.sessions["plan"]
    assert recorded.route == ("context", "planner", "critic", "explainer", "approval")
    assert len(recorded.cassettes) == 5, "the reading, three planner steps, the explanation"
    assert {path.stem for path in cassette_paths(tmp_path)} == set(recorded.cassettes)
    assert [(r.number, r.explanation) for r in recorded.revisions] == [(1, ExplanationSource.LLM)]
    assert read_manifest(tmp_path) == manifest
    assert manifest.planning_settings == SETTINGS
    assert await check_cassettes([script()], data, tmp_path, planning()) == []


async def test_a_clarification_is_answered_as_scripted_and_both_readings_are_recorded(
    data: InMemoryRetailData, tmp_path: Path
) -> None:
    clarify = script("clarify", VAGUE, {"answers": {"marketing_budget": "₹20k"}})
    live = FakeProvider(
        [reading(budget=None), reading(), *round_turns(await request_for(data)), GROUNDED]
    )

    manifest = await record_cassettes([clarify], live, data, tmp_path, planning())

    recorded = manifest.sessions["clarify"]
    assert recorded.route[:4] == ("context", "clarify", "clarify", "context")
    assert recorded.route[-1] == "approval"
    assert len(recorded.cassettes) == 6
    assert await check_cassettes([clarify], data, tmp_path, planning()) == []


async def test_amendments_and_an_approval_are_played_and_each_revision_is_recorded(
    data: InMemoryRetailData, tmp_path: Path
) -> None:
    amended = script("demo", BRIEF, {"amend": "Cut the budget to ₹10k"}, {"approve": True})
    live = FakeProvider(
        [
            reading(),
            *round_turns(await request_for(data)),
            GROUNDED,
            reading(budget=10_000.0),
            *round_turns(await request_for(data, budget=10_000.0)),
            CHANGED,
        ]
    )

    manifest = await record_cassettes([amended], live, data, tmp_path, planning())

    recorded = manifest.sessions["demo"]
    assert recorded.route[-2:] == ("approval", "done")
    assert [r.number for r in recorded.revisions] == [1, 2]
    assert await check_cassettes([amended], data, tmp_path, planning()) == []


async def test_a_regenerated_explanation_records_both_answers_and_replays(
    data: InMemoryRetailData, tmp_path: Path
) -> None:
    live = FakeProvider([reading(), *round_turns(await request_for(data)), UNGROUNDED, GROUNDED])

    manifest = await record_cassettes([script()], live, data, tmp_path, planning())

    assert len(manifest.sessions["plan"].cassettes) == 6
    assert ungrounded_answers(cassette_paths(tmp_path)) == [], "only the shown answer counts"
    assert await check_cassettes([script()], data, tmp_path, planning()) == []


# --- a session that does not play as scripted changes nothing --------------------------------


def old_cassettes(directory: Path) -> set[str]:
    stale = directory / f"{'a' * 64}.json"
    stale.write_text("{}", encoding="utf-8")
    return names(directory)


class ThenDown:
    """Answers from a script, then is down for good: whatever the script leaves out falls
    back."""

    def __init__(self, script: list[BaseModel | Exception]) -> None:
        self._fake = FakeProvider(script)
        self._left = len(script)

    async def complete_structured[T: BaseModel](
        self, schema: type[T], messages: Sequence[Message]
    ) -> T:
        self._take()
        return await self._fake.complete_structured(schema, messages)

    async def complete_with_tools(
        self, tools: Sequence[ToolSpec], messages: Sequence[Message]
    ) -> ToolTurn:
        self._take()
        return await self._fake.complete_with_tools(tools, messages)

    def _take(self) -> None:
        if not self._left:
            raise LLMError("the LLM is down in this test")
        self._left -= 1


@pytest.mark.parametrize(
    ("brief", "steps", "live", "message"),
    [
        pytest.param(
            VAGUE,
            (),
            [reading(budget=None)],
            "which the script does not answer",
            id="an unscripted question",
        ),
        pytest.param(
            VAGUE,
            ({"answers": {"promo_window": "weeks 54-55"}},),
            [reading(budget=None)],
            "the session asked",
            id="an answer to a question not asked",
        ),
        pytest.param(
            VAGUE,
            ({"approve": True},),
            [reading(budget=None)],
            "decides on the plan, but the session is at clarify",
            id="a step the session is not waiting for",
        ),
        pytest.param(BRIEF, (), [], "read the brief by rules", id="a reading by rules"),
        pytest.param(
            BRIEF,
            (),
            [reading(), finish("No plan."), finish("Still none.")],
            r"fell back to the default sequence \(no_optimised_plan\)",
            id="a degraded planner",
        ),
    ],
)
async def test_a_session_that_does_not_play_as_scripted_fails_the_run_and_changes_nothing(
    data: InMemoryRetailData,
    tmp_path: Path,
    brief: str,
    steps: tuple[dict[str, object], ...],
    live: list[BaseModel | Exception],
    message: str,
) -> None:
    before = old_cassettes(tmp_path)

    with pytest.raises(RecordingError, match=message):
        await record_cassettes(
            [script("plan", brief, *steps)], ThenDown(live), data, tmp_path, planning()
        )

    assert names(tmp_path) == before


async def test_an_explanation_that_falls_back_to_the_template_fails_the_run(
    data: InMemoryRetailData, tmp_path: Path
) -> None:
    before = old_cassettes(tmp_path)
    live = FakeProvider([reading(), *round_turns(await request_for(data)), UNGROUNDED, UNGROUNDED])

    with pytest.raises(
        RecordingError, match="Explainer fell back to the template \\(ungrounded\\)"
    ):
        await record_cassettes([script()], live, data, tmp_path, planning())

    assert names(tmp_path) == before


# --- pruning, and re-recording some sessions -------------------------------------------------


async def test_a_full_run_removes_stale_cassettes_and_keeps_other_files(
    data: InMemoryRetailData, tmp_path: Path
) -> None:
    stale = tmp_path / f"{'a' * 64}.json"
    stale.write_text("{}", encoding="utf-8")
    sessions = tmp_path / "sessions.json"
    sessions.write_text("[]", encoding="utf-8")
    live = FakeProvider([reading(), *round_turns(await request_for(data)), GROUNDED])

    await record_cassettes([script()], live, data, tmp_path, planning())

    assert stale.name not in names(tmp_path)
    assert {sessions.name, MANIFEST} <= names(tmp_path)


async def test_only_re_records_the_named_sessions_and_keeps_the_others(
    data: InMemoryRetailData, tmp_path: Path
) -> None:
    first, second = (
        script("first"),
        script("second", VAGUE, {"answers": {"marketing_budget": "₹20k"}}),
    )
    turns = round_turns(await request_for(data))
    both = FakeProvider(
        [reading(), *turns, GROUNDED, reading(budget=None), reading(), *turns, GROUNDED]
    )
    before = await record_cassettes([first, second], both, data, tmp_path, planning())
    reworded = GROUNDED.model_copy(update={"summary": "One Snacks line in North from W54."})

    after = await record_cassettes(
        [first, second],
        FakeProvider([reading(budget=None), reading(), *turns, reworded]),
        data,
        tmp_path,
        planning(),
        only=["second"],
    )

    assert after.sessions["first"] == before.sessions["first"]
    assert manifest_problems([first, second], tmp_path) == []
    assert await check_cassettes([first, second], data, tmp_path, planning()) == []


async def test_only_needs_the_others_recorded_with_the_same_planning_settings(
    data: InMemoryRetailData, tmp_path: Path
) -> None:
    live = FakeProvider([reading(), *round_turns(await request_for(data)), GROUNDED])
    await record_cassettes([script()], live, data, tmp_path, planning())

    with pytest.raises(RecordingError, match="record every session"):
        await record_cassettes(
            [script()],
            FakeProvider([]),
            data,
            tmp_path,
            planning({"simulation_runs": 200}),
            only=["plan"],
        )
    with pytest.raises(RecordingError, match="no session script is named nope"):
        await record_cassettes(
            [script()], FakeProvider([]), data, tmp_path, planning(), only=["nope"]
        )


# --- checking the cassettes -------------------------------------------------------------------


@pytest.fixture
async def recorded(data: InMemoryRetailData, tmp_path: Path) -> Path:
    live = FakeProvider([reading(), *round_turns(await request_for(data)), GROUNDED])
    await record_cassettes([script()], live, data, tmp_path, planning())
    return tmp_path


async def test_the_check_names_a_missing_cassette_and_what_fell_back(
    data: InMemoryRetailData, recorded: Path
) -> None:
    manifest = read_manifest(recorded)
    assert manifest is not None
    explanation = manifest.sessions["plan"].cassettes[-1]
    (recorded / f"{explanation}.json").unlink()

    problems = await check_cassettes([script()], data, recorded, planning())

    assert f"cassette {explanation} is listed but missing" in problems
    assert any(f"no cassette for request {explanation}" in p for p in problems)
    assert any("Explainer fell back to the template (llm_unavailable)" in p for p in problems)


async def test_the_check_reports_a_changed_script_and_other_planning_settings(
    data: InMemoryRetailData, recorded: Path
) -> None:
    changed = script("plan", BRIEF, {"approve": True})

    problems = await check_cassettes([changed], data, recorded, planning({"optimizer_seed": 1}))

    assert "session 'plan' was recorded with another script" in problems
    assert any(
        "other settings than the recording: optimizer_seed, simulation_runs" in p for p in problems
    )


def test_the_manifest_check_needs_a_manifest(tmp_path: Path) -> None:
    assert manifest_problems([script()], tmp_path) == [
        f"no {MANIFEST} in {tmp_path}: run `make record-cassettes`"
    ]


async def test_the_manifest_check_finds_a_cassette_no_session_lists(recorded: Path) -> None:
    orphan = recorded / f"{'b' * 64}.json"
    orphan.write_text("{}", encoding="utf-8")

    problems = manifest_problems([script(), script("other")], recorded)

    assert problems == [
        "session 'other' was never recorded",
        f"cassette {'b' * 64} belongs to no session",
    ]


# --- grounding over recorded answers (SPEC §13.4) --------------------------------------------


async def explainer_cassettes(
    directory: Path, answers: list[ExplainerAnswer], data: InMemoryRetailData
) -> list[Path]:
    request = await request_for(data)
    live = FakeProvider([reading(), *round_turns(request), *answers])
    await record_cassettes([script()], live, data, directory, planning())
    return cassette_paths(directory)


async def test_an_ungrounded_number_in_a_shown_explanation_is_found(
    data: InMemoryRetailData, tmp_path: Path
) -> None:
    cassettes = await explainer_cassettes(tmp_path, [GROUNDED], data)
    explainer = next(
        p for p in cassettes if json.loads(p.read_text("utf-8"))["schema_name"] == "ExplainerAnswer"
    )
    cassette = json.loads(explainer.read_text("utf-8"))
    cassette["response"]["summary"] = "Adds ₹7,000 in profit."
    explainer.write_text(json.dumps(cassette), encoding="utf-8")

    assert ungrounded_answers(cassettes) == [f"{explainer.stem}: the summary cites ₹7,000"]


async def test_critic_feedback_must_cite_only_its_findings_numbers(tmp_path: Path) -> None:
    findings = [
        {"finding": 1, "code": "heavy_cannibalisation", "message": "Line 2 loses 42% to line 1."},
        {"finding": 2, "code": "stockout_risk", "message": "Stock-out probability is 35%."},
    ]
    answer = CriticFeedback(
        feedback=[
            FindingFeedback(finding=1, feedback="Drop line 2, which loses 42% to line 1."),
            FindingFeedback(finding=2, feedback="Cut its depth: the stock-out risk is 50%."),
        ]
    )
    messages = [
        Message(role="system", content="The Critic's prompt."),
        Message(role="user", content=f"Risk findings (JSON):\n{json.dumps(findings)}"),
    ]
    await RecordingProvider(FakeProvider([answer]), tmp_path).complete_structured(
        CriticFeedback, messages
    )

    [cassette] = cassette_paths(tmp_path)
    assert ungrounded_answers([cassette]) == [f"{cassette.stem}: the finding 2 cites 50%"]


# --- session scripts ----------------------------------------------------------------------------


def test_session_scripts_load_with_their_steps(tmp_path: Path) -> None:
    path = tmp_path / "sessions.json"
    path.write_text(
        json.dumps(
            [
                {"name": "e2e", "brief": BRIEF},
                {
                    "name": "demo",
                    "brief": BRIEF,
                    "steps": [{"amend": "Drop West"}, {"approve": True}],
                },
            ]
        ),
        encoding="utf-8",
    )

    e2e, demo = load_scripts(path)

    assert e2e.steps == ()
    assert [step.amend for step in demo.steps] == ["Drop West", None]
    assert demo.steps[1].approve


@pytest.mark.parametrize(
    "sessions",
    [
        [{"name": "a", "brief": BRIEF, "steps": [{"amend": "Drop West", "approve": True}]}],
        [{"name": "a", "brief": BRIEF, "steps": [{}]}],
        [{"name": "a", "brief": BRIEF}, {"name": "a", "brief": VAGUE}],
        [{"name": "Not A Slug", "brief": BRIEF}],
    ],
)
def test_a_step_is_exactly_one_thing_and_names_are_unique_slugs(
    tmp_path: Path, sessions: list[dict[str, object]]
) -> None:
    path = tmp_path / "sessions.json"
    path.write_text(json.dumps(sessions), encoding="utf-8")

    with pytest.raises((ValidationError, ValueError)):
        load_scripts(path)


async def test_with_no_manifest_the_check_still_replays_and_names_each_miss(
    data: InMemoryRetailData, tmp_path: Path
) -> None:
    problems = await check_cassettes([script()], data, tmp_path, planning())

    assert problems[0] == f"no {MANIFEST} in {tmp_path}: run `make record-cassettes`"
    assert any("read the brief by rules (cassette_missing)" in p for p in problems)
    assert any("(BriefReading)" in p for p in problems)


# --- a request asked twice keeps one answer ----------------------------------------------------


async def test_two_sessions_asking_the_same_request_share_one_answer_and_both_replay(
    data: InMemoryRetailData, tmp_path: Path
) -> None:
    # Both sessions read the brief the same way and plan the same revision, so their Explainer
    # requests are one request. A live model may word it differently the second time; the
    # recorder answers it from the first cassette, so both sessions replay (ADR 0054).
    first, second = script("first"), script("second", BRIEF, {"approve": True})
    turns = round_turns(await request_for(data))
    reworded = GROUNDED.model_copy(update={"summary": "One Snacks line in North from W54."})
    live = FakeProvider([reading(), *turns, GROUNDED, reading(), *turns, reworded])

    manifest = await record_cassettes([first, second], live, data, tmp_path, planning())

    assert manifest.sessions["first"].cassettes == manifest.sessions["second"].cassettes
    assert await check_cassettes([first, second], data, tmp_path, planning()) == []


async def test_only_answers_a_request_a_kept_session_recorded_from_its_cassette(
    data: InMemoryRetailData, tmp_path: Path
) -> None:
    first, second = script("first"), script("second", BRIEF, {"approve": True})
    turns = round_turns(await request_for(data))
    await record_cassettes(
        [first, second],
        FakeProvider([reading(), *turns, GROUNDED]),
        data,
        tmp_path,
        planning(),
    )
    reworded = GROUNDED.model_copy(update={"summary": "One Snacks line in North from W54."})

    await record_cassettes(
        [first, second],
        FakeProvider([reading(), *turns, reworded]),
        data,
        tmp_path,
        planning(),
        only=["second"],
    )

    assert await check_cassettes([first, second], data, tmp_path, planning()) == []


# --- accepting a relaxation, as the API does (ADR 0052 D7, ADR 0070) --------------------------

RELAXED_BUDGET = 21_000.0
"""What accepting the relaxation raises the ₹20k budget to; code applies it (ADR 0083)."""
RELAXATION = Relaxation(
    changes=(
        RelaxedConstraint(
            kind=ConstraintKind.MARKETING_BUDGET,
            current=20_000.0,
            relaxed=RELAXED_BUDGET,
            change=0.05,
        ),
    ),
    policy_binds=False,
    proven=True,
)
ACCEPTED = "Accept the smallest relaxation: raise the marketing budget to ₹21,000.00."


def infeasible() -> PlannedRevision:
    """Plan revision 1, infeasible: its marketing budget is too small (ADR 0044)."""
    base = planned()
    revision = base.revision.model_copy(
        update={
            "solver_status": SolveStatus.INFEASIBLE,
            "relaxation": RELAXATION,
            "binding_constraints": (
                BindingConstraint(
                    kind=ConstraintKind.MARKETING_BUDGET,
                    source=ConstraintSource.BRIEF,
                    limit=20_000.0,
                    region=None,
                    sku_id=None,
                    evidence=BindingEvidence.INFEASIBLE,
                    objective_gain=None,
                ),
            ),
        }
    )
    return PlannedRevision(revision, base.facts)


class InTurn:
    """The plan revision of each planning round in turn; the last one stays."""

    def __init__(self, *revisions: PlannedRevision) -> None:
        self._revisions = list(revisions)

    async def revision(self, candidate_set_id: UUID) -> PlannedRevision | None:
        return self._revisions.pop(0) if len(self._revisions) > 1 else self._revisions[0]


def planning_in_turn(*revisions: PlannedRevision) -> RecordedPlanning:
    tools = ScriptedTools(
        {
            "generate_candidates": [Generated(candidate_set_id=SET_ID)],
            "run_optimizer": [optimised()],
        }
    )
    return RecordedPlanning(
        agent=AgentTools(tools=tools, revisions=InTurn(*revisions)),
        default=ScriptedPlanner(planned(promo_cost=900.0)),
        settings=SETTINGS,
    )


async def accepted_round(data: InMemoryRetailData) -> list[BaseModel]:
    """The live answers of the round that accepts the relaxation. The LLM never reads the
    accept, so the brief is asked as in round 1 and replays from its cassette; code raises the
    budget, so the planner and the Explainer are asked anew (ADR 0083)."""
    relaxed = await request_for(data, budget=RELAXED_BUDGET)
    return [*round_turns(relaxed), CHANGED]


async def test_accepting_the_relaxation_re_plans_and_the_feasible_revision_is_approved(
    data: InMemoryRetailData, tmp_path: Path
) -> None:
    demo = script("demo", BRIEF, {"accept_relaxation": True}, {"approve": True})
    live = FakeProvider(
        [
            reading(),
            *round_turns(await request_for(data)),
            GROUNDED,
            *await accepted_round(data),
        ]
    )

    manifest = await record_cassettes(
        [demo], live, data, tmp_path, planning_in_turn(infeasible(), planned())
    )

    recorded = manifest.sessions["demo"]
    assert recorded.amendments == (ACCEPTED,)
    assert recorded.route[-2:] == ("approval", "done")
    assert [r.number for r in recorded.revisions] == [1, 2]
    assert (
        await check_cassettes([demo], data, tmp_path, planning_in_turn(infeasible(), planned()))
        == []
    )


async def test_approving_an_infeasible_revision_fails_the_run_as_the_api_refuses_it(
    data: InMemoryRetailData, tmp_path: Path
) -> None:
    before = old_cassettes(tmp_path)
    live = FakeProvider([reading(), *round_turns(await request_for(data)), GROUNDED])

    with pytest.raises(
        RecordingError, match="step 1 approves plan revision 1, which is infeasible"
    ):
        await record_cassettes(
            [script("demo", BRIEF, {"approve": True})],
            live,
            data,
            tmp_path,
            planning_in_turn(infeasible()),
        )

    assert names(tmp_path) == before


async def test_accepting_a_relaxation_the_revision_does_not_have_fails_the_run(
    data: InMemoryRetailData, tmp_path: Path
) -> None:
    before = old_cassettes(tmp_path)
    live = FakeProvider([reading(), *round_turns(await request_for(data)), GROUNDED])

    with pytest.raises(RecordingError, match="plan revision 1 has no relaxation to accept"):
        await record_cassettes(
            [script("demo", BRIEF, {"accept_relaxation": True})],
            live,
            data,
            tmp_path,
            planning(),
        )

    assert names(tmp_path) == before


async def test_the_check_refuses_an_infeasible_approval_too(
    data: InMemoryRetailData, tmp_path: Path
) -> None:
    planned_only = script("demo")
    live = FakeProvider([reading(), *round_turns(await request_for(data)), GROUNDED])
    await record_cassettes([planned_only], live, data, tmp_path, planning_in_turn(infeasible()))
    approved = script("demo", BRIEF, {"approve": True})

    problems = await check_cassettes([approved], data, tmp_path, planning_in_turn(infeasible()))

    assert any("step 1 approves plan revision 1, which is infeasible" in p for p in problems)


async def test_only_extends_a_named_session_asking_the_live_model_only_its_new_round(
    data: InMemoryRetailData, tmp_path: Path
) -> None:
    # The demo gains a step: its earlier rounds keep their recorded answers byte for byte, and
    # only the new round is asked live (ADR 0070).
    other = script("other", VAGUE, {"answers": {"marketing_budget": "₹20k"}})
    planned_first = script("demo")
    turns = round_turns(await request_for(data))
    await record_cassettes(
        [other, planned_first],
        FakeProvider(
            [reading(budget=None), reading(), *turns, GROUNDED, reading(), *turns, GROUNDED]
        ),
        data,
        tmp_path,
        planning_in_turn(infeasible()),
    )
    before = {path.name: path.read_bytes() for path in cassette_paths(tmp_path)}
    extended = script("demo", BRIEF, {"accept_relaxation": True}, {"approve": True})

    manifest = await record_cassettes(
        [other, extended],
        FakeProvider(await accepted_round(data)),
        data,
        tmp_path,
        planning_in_turn(infeasible(), planned()),
        only=["demo"],
    )

    after = {path.name: path.read_bytes() for path in cassette_paths(tmp_path)}
    assert {name: after.get(name) for name in before} == before
    # The round's reading replays from round 1's cassette: the LLM never reads the accept.
    assert len(after) == len(before) + 4, "three planner steps, the explanation"
    assert manifest.sessions["demo"].amendments == (ACCEPTED,)
    assert manifest_problems([other, extended], tmp_path) == []


def test_a_script_may_accept_the_relaxation_but_not_with_another_thing_in_one_step(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sessions.json"
    steps = [{"accept_relaxation": True}, {"approve": True}]
    path.write_text(json.dumps([{"name": "demo", "brief": BRIEF, "steps": steps}]), "utf-8")

    [demo] = load_scripts(path)

    assert [step.accept_relaxation for step in demo.steps] == [True, False]
    with pytest.raises(ValidationError):
        SessionScript.model_validate(
            {"name": "a", "brief": BRIEF, "steps": [{"accept_relaxation": True, "amend": "x"}]}
        )
