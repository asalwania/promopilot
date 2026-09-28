"""Record, and check, the LLM cassettes that let whole planning sessions replay with no API key
(ADR 0019, ADR 0022, ADR 0054).

A **session script** names a brief and what the manager does after it: answer the Clarify
interrupt's questions, amend the plan, approve it. `record_cassettes` plays each script through
the full agent graph (Context, Clarify, Planner, Critic, Explainer, Approval) on a live
provider, recording every LLM request as a cassette, and writes a manifest of what each
session called. `check_cassettes` plays the same scripts on the cassettes alone and reports
every miss or fallback, so CI proves the stack replays whole sessions.

A recording is refused, and nothing changes, when any session falls back: the Context agent
read by rules, a question the script does not answer, the planner agent degrading to the
default sequence, the Explainer falling back to its template, or LLM text that cites a number
its data does not show (SPEC §13.4).
"""

import json
import shutil
import tempfile
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self
from uuid import UUID, uuid4

from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from promopilot.agents.critic import CriticFeedback
from promopilot.agents.explainer import ExplainerAnswer
from promopilot.agents.graph import (
    GraphSnapshot,
    GraphTools,
    PlanningGraph,
    build_graph,
    checkpoint_serializer,
    graph_state,
    resume_with_amendment,
    resume_with_answers,
    resume_with_decision,
    start_planning,
)
from promopilot.agents.planner_agent import AgentTools, DefaultSequence
from promopilot.agents.session import BriefData
from promopilot.domain import (
    Assumption,
    CompanyPolicy,
    DecisionKind,
    ExplanationSource,
    OpenIssue,
    PlanDecision,
    PlanExplanation,
    PlanningRequest,
    PlanRevision,
)
from promopilot.guardrails import RiskThresholds, check_numeric_grounding
from promopilot.llm import (
    CassetteMissError,
    LLMProvider,
    Message,
    RecordingProvider,
    ReplayProvider,
    ToolSpec,
    ToolTurn,
    cassette_paths,
    request_hash,
    tool_request_hash,
)

MANIFEST = "manifest.json"
"""The manifest's file name, next to the cassettes."""


class RecordingError(Exception):
    """A session could not be recorded as scripted, so no cassette was changed."""


# ---------------------------------------------------------------- session scripts


class ScriptStep(BaseModel):
    """One thing the manager does while the graph waits: exactly one of answer the Clarify
    interrupt's questions (by question id), amend the plan, or approve it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    answers: dict[str, str] | None = None
    amend: str | None = None
    approve: bool = False

    @model_validator(mode="after")
    def _exactly_one(self) -> Self:
        chosen = [self.answers is not None, self.amend is not None, self.approve]
        if chosen.count(True) != 1:
            raise ValueError("a step is exactly one of answers, amend or approve")
        return self


class SessionScript(BaseModel):
    """A recorded session: the brief, then each step, in order."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    brief: str = Field(min_length=1)
    steps: tuple[ScriptStep, ...] = ()


_SCRIPTS: TypeAdapter[list[SessionScript]] = TypeAdapter(list[SessionScript])


def load_scripts(path: Path) -> list[SessionScript]:
    """The session scripts in `path` (`cassettes/sessions.json`), with unique names."""
    scripts = _SCRIPTS.validate_json(path.read_bytes())
    names = [script.name for script in scripts]
    duplicated = sorted({name for name in names if names.count(name) > 1})
    if duplicated:
        raise ValueError(f"session names must be unique: {', '.join(duplicated)}")
    return scripts


# ---------------------------------------------------------------- the manifest


class RecordedRevision(BaseModel):
    model_config = ConfigDict(frozen=True)

    number: int
    explanation: ExplanationSource


class RecordedSession(BaseModel):
    """What a session called when it was recorded."""

    model_config = ConfigDict(frozen=True)

    script: SessionScript
    route: tuple[str, ...]
    """The nodes it ran, in order, with the interrupts it paused at."""
    cassettes: tuple[str, ...]
    """The request hash of every LLM call, in call order, each once."""
    revisions: tuple[RecordedRevision, ...]


class CassetteManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    planning_settings: dict[str, Any]
    """The settings that shape what the LLM is shown (solver, simulation, Critic thresholds):
    a stack that plans with others cannot replay the sessions (ADR 0054)."""
    sessions: dict[str, RecordedSession]


def read_manifest(cassette_dir: Path) -> CassetteManifest | None:
    path = cassette_dir.joinpath(MANIFEST)
    if not path.is_file():
        return None
    return CassetteManifest.model_validate_json(path.read_bytes())


def manifest_problems(scripts: Sequence[SessionScript], cassette_dir: Path) -> list[str]:
    """Why the cassettes in `cassette_dir` are not the recording of `scripts`: a session
    recorded with another script or not at all, a listed cassette missing, or a cassette no
    session lists. Checked without replaying anything."""
    manifest = read_manifest(cassette_dir)
    if manifest is None:
        return [f"no {MANIFEST} in {cassette_dir}: run `make record-cassettes`"]
    problems = []
    for script in scripts:
        recorded = manifest.sessions.get(script.name)
        if recorded is None:
            problems.append(f"session {script.name!r} was never recorded")
        elif recorded.script != script:
            problems.append(f"session {script.name!r} was recorded with another script")
    listed = {digest for session in manifest.sessions.values() for digest in session.cassettes}
    present = {path.stem for path in cassette_paths(cassette_dir)}
    problems.extend(
        f"cassette {d} is listed but missing" for d in sorted(listed.difference(present))
    )
    problems.extend(
        f"cassette {d} belongs to no session" for d in sorted(present.difference(listed))
    )
    return problems


# ---------------------------------------------------------------- playing a script


@dataclass(frozen=True)
class RecordedPlanning:
    """What the graph plans with besides the LLM: the planner agent's tools, the default
    sequence, company policy, the Critic's thresholds, and the planning settings the manifest
    records (`promopilot.api.planning`)."""

    agent: AgentTools
    default: DefaultSequence
    policy: CompanyPolicy = field(default_factory=CompanyPolicy)
    risk_thresholds: RiskThresholds = field(default_factory=RiskThresholds)
    settings: Mapping[str, Any] = field(default_factory=dict)


class _HashLog:
    """Notes the request hash of every call, and every one that missed a cassette."""

    def __init__(self, inner: LLMProvider) -> None:
        self._inner = inner
        self.hashes: list[str] = []
        self.missed: list[str] = []

    async def complete_structured[T: BaseModel](
        self, schema: type[T], messages: Sequence[Message]
    ) -> T:
        digest = request_hash(schema, messages)
        self.hashes.append(digest)
        try:
            return await self._inner.complete_structured(schema, messages)
        except CassetteMissError:
            self.missed.append(f"{digest} ({schema.__name__})")
            raise

    async def complete_with_tools(
        self, tools: Sequence[ToolSpec], messages: Sequence[Message]
    ) -> ToolTurn:
        digest = tool_request_hash(tools, messages)
        self.hashes.append(digest)
        try:
            return await self._inner.complete_with_tools(tools, messages)
        except CassetteMissError:
            self.missed.append(f"{digest} (planner step)")
            raise


class _Sessions:
    """The session read model, which a recording does not keep."""

    async def save_assumptions(self, session_id: UUID, assumptions: tuple[Assumption, ...]) -> None:
        return None

    async def save_revision(
        self, session_id: UUID, request: PlanningRequest, revision: PlanRevision
    ) -> None:
        return None

    async def save_open_issues(
        self, session_id: UUID, revision_number: int, issues: tuple[OpenIssue, ...]
    ) -> None:
        return None

    async def save_explanation(
        self, session_id: UUID, revision_number: int, explanation: PlanExplanation
    ) -> None:
        return None

    async def record_decision(
        self, session_id: UUID, decision: DecisionKind, revision_number: int, reason: str | None
    ) -> PlanDecision:
        return PlanDecision(
            decision=decision,
            revision_number=revision_number,
            reason=reason,
            decided_at=datetime.now(UTC),
        )


@dataclass
class _Played:
    session: RecordedSession
    problems: list[str]


async def _play(
    script: SessionScript, llm: LLMProvider, data: BriefData, planning: RecordedPlanning
) -> _Played:
    logged = _HashLog(llm)
    tools = GraphTools(
        brief_data=data,
        planner=planning.default,
        sessions=_Sessions(),
        policy=planning.policy,
        agent=planning.agent,
        risk_thresholds=planning.risk_thresholds,
    )
    graph = build_graph(tools, logged, InMemorySaver(serde=checkpoint_serializer()))
    session_id = uuid4()
    thread = str(session_id)
    route = await start_planning(graph, thread, session_id, script.brief)
    snapshot = await _snapshot(graph, thread)
    problems = _fallbacks(snapshot)
    revisions = _revisions([], snapshot)
    for number, step in enumerate(script.steps, start=1):
        if problems:
            break
        where = f"step {number}"
        if step.answers is not None:
            if not snapshot.awaits_clarification:
                problems.append(f"{where} answers questions, but the session is at {_at(snapshot)}")
                break
            asked = {question.id: question.question for question in snapshot.values.questions}
            if set(asked) != set(step.answers):
                problems.append(
                    f"{where} answers {sorted(step.answers)}, but the session asked {asked}"
                )
                break
            route.extend(await resume_with_answers(graph, thread, step.answers))
        elif not snapshot.awaits_decision:
            problems.append(f"{where} decides on the plan, but the session is at {_at(snapshot)}")
            break
        elif step.amend is not None:
            route.extend(await resume_with_amendment(graph, thread, step.amend))
        else:
            revision = snapshot.values.plan
            if revision is None:
                raise RuntimeError("the session awaits a decision without a plan revision")
            route.extend(
                await resume_with_decision(
                    graph,
                    thread,
                    DecisionKind.APPROVED,
                    revision_number=revision.number,
                    reason=None,
                )
            )
            snapshot = await _snapshot(graph, thread)
            continue
        snapshot = await _snapshot(graph, thread)
        problems.extend(_fallbacks(snapshot))
        revisions = _revisions(revisions, snapshot)
    if not problems and snapshot.awaits_clarification:
        asked = {question.id: question.question for question in snapshot.values.questions}
        problems.append(f"the session asked {asked}, which the script does not answer")
    problems.extend(f"no cassette for request {missed}" for missed in logged.missed)
    session = RecordedSession(
        script=script,
        route=tuple(route),
        cassettes=tuple(dict.fromkeys(logged.hashes)),
        revisions=tuple(revisions),
    )
    return _Played(session, [f"session {script.name!r}: {problem}" for problem in problems])


async def _snapshot(graph: PlanningGraph, thread: str) -> GraphSnapshot:
    snapshot = await graph_state(graph, thread)
    if snapshot is None:
        raise RuntimeError("the session has no checkpoint")
    return snapshot


def _at(snapshot: GraphSnapshot) -> str:
    return ", ".join(snapshot.paused_at) or "its end"


def _fallbacks(snapshot: GraphSnapshot) -> list[str]:
    """What fell back in the run that led to `snapshot`: only the LLM's own work is recorded."""
    state = snapshot.values
    problems = []
    if state.context_degraded is not None:
        problems.append(f"the Context agent read the brief by rules ({state.context_degraded})")
    if snapshot.awaits_decision:
        problems += [
            f"the planner agent fell back to the default sequence ({attempt.degraded})"
            for attempt in state.attempts
            if attempt.degraded is not None
        ]
        explanation = state.explanations
        if explanation is not None and explanation.fallback_reason is not None:
            problems.append(
                f"the Explainer fell back to the template ({explanation.fallback_reason})"
            )
    return problems


def _revisions(
    revisions: list[RecordedRevision], snapshot: GraphSnapshot
) -> list[RecordedRevision]:
    state = snapshot.values
    if not snapshot.awaits_decision or state.plan is None or state.explanations is None:
        return revisions
    if any(revision.number == state.plan.number for revision in revisions):
        return revisions
    return [
        *revisions,
        RecordedRevision(number=state.plan.number, explanation=state.explanations.source),
    ]


# ---------------------------------------------------------------- grounding over cassettes


def ungrounded_answers(cassettes: Sequence[Path]) -> list[str]:
    """Every number in the recorded Explainer and Critic answers that their own request's tool
    data does not show (`check_numeric_grounding`, SPEC §13.4). An Explainer answer that was
    regenerated is left out: only the answer it was replaced with was shown."""
    loaded = [json.loads(path.read_text(encoding="utf-8")) for path in cassettes]
    explained = [c for c in loaded if c["schema_name"] == ExplainerAnswer.__name__]
    problems = []
    for cassette in explained:
        messages = cassette["request"]["messages"]
        if any(_extends(other["request"]["messages"], messages) for other in explained):
            continue
        data = _data(messages)
        answer = ExplainerAnswer.model_validate(cassette["response"])
        texts = [
            ("summary", answer.summary),
            *((f"rationale {item.line}", item.rationale) for item in answer.rationales),
            ("changes", answer.changes or ""),
        ]
        problems.extend(_ungrounded(cassette["hash"], texts, data))
    for cassette in loaded:
        if cassette["schema_name"] != CriticFeedback.__name__:
            continue
        findings = _data(cassette["request"]["messages"])
        written = {
            item.finding: item.feedback
            for item in CriticFeedback.model_validate(cassette["response"]).feedback
        }
        for shown in findings:
            text = written.get(shown["finding"], "").strip()
            if not text:
                problems.append(f"{cassette['hash']}: no feedback for finding {shown['finding']}")
                continue
            where = f"finding {shown['finding']}"
            problems.extend(_ungrounded(cassette["hash"], [(where, text)], shown))
    return problems


def _extends(longer: list[Any], shorter: list[Any]) -> bool:
    return len(longer) > len(shorter) and longer[: len(shorter)] == shorter


def _data(messages: list[dict[str, Any]]) -> Any:
    """The JSON tool data a prompt's user message shows after its one-line heading."""
    shown = next(message["content"] for message in messages if message["role"] == "user")
    return json.loads(shown.split("\n", 1)[1])


def _ungrounded(digest: str, texts: list[tuple[str, str]], data: object) -> list[str]:
    problems = []
    for where, text in texts:
        report = check_numeric_grounding(text, data)
        if not report.grounded:
            problems.append(f"{digest}: the {where} cites {', '.join(report.ungrounded)}")
    return problems


# ---------------------------------------------------------------- record and check


async def record_cassettes(
    scripts: Sequence[SessionScript],
    live: LLMProvider,
    data: BriefData,
    cassette_dir: Path,
    planning: RecordedPlanning,
    *,
    only: Collection[str] | None = None,
) -> CassetteManifest:
    """Play every script (or those named in `only`) through the full agent graph on `live`,
    recording each LLM request as a cassette, and write the manifest.

    Cassettes are recorded into a scratch directory and replace those in `cassette_dir` only
    once every session played as scripted with nothing falling back, so a failed run changes
    nothing. Then every cassette no recorded session lists is removed, so none goes stale.
    With `only`, the other sessions keep their recording. Other files are kept.
    """
    chosen = [script for script in scripts if only is None or script.name in only]
    unknown = sorted(set(only or ()).difference(script.name for script in scripts))
    if unknown:
        raise RecordingError(f"no session script is named {', '.join(unknown)}")
    kept: dict[str, RecordedSession] = {}
    if only is not None:
        previous = read_manifest(cassette_dir)
        if previous is None or dict(previous.planning_settings) != dict(planning.settings):
            raise RecordingError(
                "re-recording some sessions needs the others recorded with these planning "
                "settings: record every session"
            )
        kept = {
            script.name: previous.sessions[script.name]
            for script in scripts
            if script.name not in only and script.name in previous.sessions
        }
    with tempfile.TemporaryDirectory() as scratch:
        recorder = RecordingProvider(live, Path(scratch))
        played = [await _play(script, recorder, data, planning) for script in chosen]
        problems = [problem for result in played for problem in result.problems]
        problems.extend(ungrounded_answers(cassette_paths(Path(scratch))))
        if problems:
            raise RecordingError("\n".join(["no cassette changed:", *problems]))
        sessions = kept | {result.session.script.name: result.session for result in played}
        manifest = CassetteManifest(
            planning_settings=dict(planning.settings),
            sessions={script.name: sessions[script.name] for script in scripts},
        )
        _replace(Path(scratch), cassette_dir, manifest)
    return manifest


def _replace(recorded: Path, cassette_dir: Path, manifest: CassetteManifest) -> None:
    cassette_dir.mkdir(parents=True, exist_ok=True)
    for cassette in cassette_paths(recorded):
        shutil.copy2(cassette, cassette_dir.joinpath(cassette.name))
    listed = {digest for session in manifest.sessions.values() for digest in session.cassettes}
    for stale in cassette_paths(cassette_dir):
        if stale.stem not in listed:
            stale.unlink()
    cassette_dir.joinpath(MANIFEST).write_text(
        manifest.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n"
    )


async def check_cassettes(
    scripts: Sequence[SessionScript],
    data: BriefData,
    cassette_dir: Path,
    planning: RecordedPlanning,
) -> list[str]:
    """Why the cassettes do not replay every scripted session as recorded; empty when they do.

    Each script plays through the full agent graph on the cassettes alone: a cassette miss, a
    fallback, another route or other planning settings than the recording's is reported.
    """
    problems = manifest_problems(scripts, cassette_dir)
    manifest = read_manifest(cassette_dir)
    recorded_settings = {} if manifest is None else dict(manifest.planning_settings)
    if manifest is not None and recorded_settings != dict(planning.settings):
        differ = sorted(
            key
            for key in {*recorded_settings, *planning.settings}
            if recorded_settings.get(key) != planning.settings.get(key)
        )
        problems.append(
            f"the stack plans with other settings than the recording: {', '.join(differ)}"
        )
    replay = ReplayProvider(cassette_dir)
    for script in scripts:
        played = await _play(script, replay, data, planning)
        problems.extend(played.problems)
        recorded = None if manifest is None else manifest.sessions.get(script.name)
        if recorded is not None and not played.problems and played.session.route != recorded.route:
            problems.append(
                f"session {script.name!r} replayed {list(played.session.route)}, "
                f"not the recorded {list(recorded.route)}"
            )
    return problems
