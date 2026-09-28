"""Persistence for planning sessions, their plan revisions, their explanations and every
decision on them (E3, E8: ADR 0046, ADR 0050), with the Context agent's assumptions and
clarifications (ADR 0048) and every amendment, each revision with its diff (ADR 0052)."""

from uuid import UUID, uuid4

from pydantic import TypeAdapter
from sqlalchemy import cast, func, insert, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncEngine

from promopilot.data.schema import approvals, plan_lines, plan_revisions, planning_sessions
from promopilot.data.trace import session_usage
from promopilot.domain import (
    Amendment,
    Assumption,
    BindingConstraint,
    Clarification,
    ClarificationQuestion,
    ClearanceShortfall,
    DecisionKind,
    LineCrossEffect,
    MechanismOutcome,
    NotSelectedOption,
    OpenIssue,
    PlanDecision,
    PlanExplanation,
    PlanLine,
    PlanningRequest,
    PlanningSession,
    PlanRevision,
    PlanRevisionLine,
    PlanSimulation,
    PolicyFinding,
    Relaxation,
    RevisionDiff,
    SegmentUplift,
    SessionStatus,
    SolveStatus,
    WhyChosen,
)

_BINDING = TypeAdapter(tuple[BindingConstraint, ...])
_NOT_SELECTED = TypeAdapter(tuple[NotSelectedOption, ...])
_COMPARISON = TypeAdapter(tuple[MechanismOutcome, ...])
_SEGMENTS = TypeAdapter(tuple[SegmentUplift, ...])
_CROSS_EFFECTS = TypeAdapter(tuple[LineCrossEffect, ...])
_SHORTFALLS = TypeAdapter(tuple[ClearanceShortfall, ...])
_FINDINGS = TypeAdapter(tuple[PolicyFinding, ...])
_ISSUES = TypeAdapter(tuple[OpenIssue, ...])
_ASSUMPTIONS = TypeAdapter(tuple[Assumption, ...])
_QUESTIONS = TypeAdapter(tuple[ClarificationQuestion, ...])
_CLARIFICATIONS = TypeAdapter(tuple[Clarification, ...])
_AMENDMENTS = TypeAdapter(tuple[Amendment, ...])

AMENDABLE = (SessionStatus.AWAITING_APPROVAL, SessionStatus.REJECTED)
"""The statuses an amendment is accepted in: the graph waits at Approval (ADR 0052)."""

INTERRUPTED = "planning was interrupted by an API restart; start a new session"


class SessionConflictError(Exception):
    """The session is not in a state that allows the change (ADR 0046): the API's 409."""


class SessionStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def create(self, brief: str) -> UUID:
        session_id = uuid4()
        async with self._engine.begin() as connection:
            await connection.execute(
                insert(planning_sessions).values(
                    id=session_id,
                    brief=brief,
                    status=SessionStatus.PLANNING.value,
                    # The agent graph's thread is the session itself (ADR 0046).
                    thread_id=str(session_id),
                )
            )
        return session_id

    async def get(self, session_id: UUID) -> PlanningSession | None:
        async with self._engine.connect() as connection:
            session = (
                await connection.execute(
                    select(planning_sessions).where(planning_sessions.c.id == session_id)
                )
            ).one_or_none()
            if session is None:
                return None
            revision = (
                await connection.execute(
                    select(plan_revisions)
                    .where(plan_revisions.c.session_id == session_id)
                    .order_by(plan_revisions.c.number.desc())
                    .limit(1)
                )
            ).one_or_none()
            latest = None if revision is None else revision.number
            lines = []
            if latest is not None:
                lines = list(
                    (
                        await connection.execute(
                            select(plan_lines)
                            .where(
                                plan_lines.c.session_id == session_id,
                                plan_lines.c.revision_number == latest,
                            )
                            .order_by(plan_lines.c.position)
                        )
                    ).mappings()
                )
            decisions = (
                await connection.execute(
                    select(approvals)
                    .where(approvals.c.session_id == session_id)
                    .order_by(approvals.c.id)
                )
            ).all()
            usage = await session_usage(connection, session_id)
        request = session.planning_request
        return PlanningSession(
            id=session.id,
            brief=session.brief,
            status=SessionStatus(session.status),
            planning_request=None if request is None else PlanningRequest.model_validate(request),
            latest_revision=None
            if revision is None
            else _revision(revision, tuple(_revision_line(row) for row in lines)),
            error=session.error,
            thread_id=session.thread_id,
            decisions=tuple(
                PlanDecision(
                    decision=DecisionKind(row.decision),
                    revision_number=row.revision_number,
                    reason=row.reason,
                    decided_at=row.decided_at,
                )
                for row in decisions
            ),
            usage=usage,
            assumptions=_ASSUMPTIONS.validate_python(session.assumptions or ()),
            questions=_QUESTIONS.validate_python(session.questions or ()),
            clarifications=_CLARIFICATIONS.validate_python(session.clarifications or ()),
            amendments=_AMENDMENTS.validate_python(session.amendments or ()),
        )

    async def save_assumptions(self, session_id: UUID, assumptions: tuple[Assumption, ...]) -> None:
        """Store the Context agent's latest assumptions; the status is unchanged."""
        async with self._engine.begin() as connection:
            await connection.execute(
                update(planning_sessions)
                .where(planning_sessions.c.id == session_id)
                .values(
                    assumptions=_ASSUMPTIONS.dump_python(assumptions, mode="json"),
                    updated_at=func.now(),
                )
            )

    async def await_clarification(
        self, session_id: UUID, questions: tuple[ClarificationQuestion, ...]
    ) -> None:
        """A `planning` session now awaits answers to these questions; any other status is
        kept (ADR 0048)."""
        async with self._engine.begin() as connection:
            await connection.execute(
                update(planning_sessions)
                .where(
                    planning_sessions.c.id == session_id,
                    planning_sessions.c.status == SessionStatus.PLANNING.value,
                )
                .values(
                    status=SessionStatus.AWAITING_CLARIFICATION.value,
                    questions=_QUESTIONS.dump_python(questions, mode="json"),
                    updated_at=func.now(),
                )
            )

    async def answer_clarifications(
        self, session_id: UUID, clarifications: tuple[Clarification, ...]
    ) -> None:
        """Keep the answered questions (every one so far, oldest first) and move a session
        awaiting clarification back to `planning`. Raises `SessionConflictError`, changing
        nothing, when it is not awaiting clarification."""
        async with self._engine.begin() as connection:
            moved = await connection.execute(
                update(planning_sessions)
                .where(
                    planning_sessions.c.id == session_id,
                    planning_sessions.c.status == SessionStatus.AWAITING_CLARIFICATION.value,
                )
                .values(
                    status=SessionStatus.PLANNING.value,
                    questions=None,
                    clarifications=_CLARIFICATIONS.dump_python(clarifications, mode="json"),
                    updated_at=func.now(),
                )
            )
            if moved.rowcount != 1:
                raise SessionConflictError(f"session {session_id} is not awaiting clarification")

    async def save_revision(
        self, session_id: UUID, request: PlanningRequest, revision: PlanRevision
    ) -> None:
        """Store the planning request and a plan revision; the status is unchanged."""
        async with self._engine.begin() as connection:
            await connection.execute(
                insert(plan_revisions).values(
                    session_id=session_id,
                    number=revision.number,
                    solver_status=None
                    if revision.solver_status is None
                    else revision.solver_status.value,
                    objective=revision.objective,
                    binding_constraints=_BINDING.dump_python(
                        revision.binding_constraints, mode="json"
                    ),
                    not_selected=_NOT_SELECTED.dump_python(revision.not_selected, mode="json"),
                    simulation=None
                    if revision.simulation is None
                    else revision.simulation.model_dump(mode="json"),
                    clearance_shortfalls=_SHORTFALLS.dump_python(
                        revision.clearance_shortfalls, mode="json"
                    ),
                    policy_findings=_FINDINGS.dump_python(revision.policy_findings, mode="json"),
                    relaxation=None
                    if revision.relaxation is None
                    else revision.relaxation.model_dump(mode="json"),
                    open_issues=_ISSUES.dump_python(revision.open_issues, mode="json"),
                    explanation=None
                    if revision.explanation is None
                    else revision.explanation.model_dump(mode="json"),
                    diff=None if revision.diff is None else revision.diff.model_dump(mode="json"),
                )
            )
            if revision.lines:
                await connection.execute(
                    insert(plan_lines),
                    [
                        _line_row(session_id, revision.number, position, line)
                        for position, line in enumerate(revision.lines)
                    ],
                )
            await connection.execute(
                update(planning_sessions)
                .where(planning_sessions.c.id == session_id)
                .values(planning_request=request.model_dump(mode="json"), updated_at=func.now())
            )

    async def save_open_issues(
        self, session_id: UUID, revision_number: int, issues: tuple[OpenIssue, ...]
    ) -> None:
        """Store the violations and risk findings the Critic left open on a plan revision."""
        async with self._engine.begin() as connection:
            await connection.execute(
                update(plan_revisions)
                .where(
                    plan_revisions.c.session_id == session_id,
                    plan_revisions.c.number == revision_number,
                )
                .values(open_issues=_ISSUES.dump_python(issues, mode="json"))
            )

    async def save_explanation(
        self, session_id: UUID, revision_number: int, explanation: PlanExplanation
    ) -> None:
        """Store the Explainer's summary and rationales on a plan revision (ADR 0050)."""
        async with self._engine.begin() as connection:
            await connection.execute(
                update(plan_revisions)
                .where(
                    plan_revisions.c.session_id == session_id,
                    plan_revisions.c.number == revision_number,
                )
                .values(explanation=explanation.model_dump(mode="json"))
            )

    async def await_approval(self, session_id: UUID) -> None:
        """A `planning` session now awaits approval; any other status is kept, so the agent
        graph can call this again when it resumes (ADR 0046)."""
        async with self._engine.begin() as connection:
            await connection.execute(
                update(planning_sessions)
                .where(
                    planning_sessions.c.id == session_id,
                    planning_sessions.c.status == SessionStatus.PLANNING.value,
                )
                .values(status=SessionStatus.AWAITING_APPROVAL.value, updated_at=func.now())
            )

    async def record_decision(
        self,
        session_id: UUID,
        decision: DecisionKind,
        revision_number: int,
        reason: str | None,
    ) -> PlanDecision:
        """Approve or reject the latest plan revision of a session awaiting approval, and keep
        the decision in its audit trail. Raises `SessionConflictError`, changing nothing, when the
        session is not awaiting approval or the revision is not its latest."""
        latest = (
            select(func.max(plan_revisions.c.number))
            .where(plan_revisions.c.session_id == session_id)
            .scalar_subquery()
        )
        async with self._engine.begin() as connection:
            moved = await connection.execute(
                update(planning_sessions)
                .where(
                    planning_sessions.c.id == session_id,
                    planning_sessions.c.status == SessionStatus.AWAITING_APPROVAL.value,
                    latest == revision_number,
                )
                .values(status=decision.value, updated_at=func.now())
            )
            if moved.rowcount != 1:
                raise SessionConflictError(
                    f"plan revision {revision_number} of session {session_id} is not awaiting "
                    "approval"
                )
            decided_at = (
                await connection.execute(
                    insert(approvals)
                    .values(
                        session_id=session_id,
                        revision_number=revision_number,
                        decision=decision.value,
                        reason=reason,
                    )
                    .returning(approvals.c.decided_at)
                )
            ).scalar_one()
        return PlanDecision(
            decision=decision,
            revision_number=revision_number,
            reason=reason,
            decided_at=decided_at,
        )

    async def amend(
        self,
        session_id: UUID,
        text: str,
        amends_revision: int,
        relaxation: Relaxation | None = None,
    ) -> Amendment:
        """Keep an amendment of the latest plan revision and move a session awaiting approval,
        or rejected, back to `planning` (ADR 0052). Raises `SessionConflictError`, changing
        nothing, when the session is in another status or the revision is not its latest."""
        latest = (
            select(func.max(plan_revisions.c.number))
            .where(plan_revisions.c.session_id == session_id)
            .scalar_subquery()
        )
        async with self._engine.begin() as connection:
            now = (await connection.execute(select(func.now()))).scalar_one()
            amendment = Amendment(
                text=text, amends_revision=amends_revision, relaxation=relaxation, amended_at=now
            )
            appended = func.coalesce(planning_sessions.c.amendments, cast([], JSONB)).op("||")(
                cast([amendment.model_dump(mode="json")], JSONB)
            )
            moved = await connection.execute(
                update(planning_sessions)
                .where(
                    planning_sessions.c.id == session_id,
                    planning_sessions.c.status.in_([status.value for status in AMENDABLE]),
                    latest == amends_revision,
                )
                .values(
                    status=SessionStatus.PLANNING.value,
                    amendments=appended,
                    updated_at=func.now(),
                )
            )
            if moved.rowcount != 1:
                raise SessionConflictError(
                    f"plan revision {amends_revision} of session {session_id} cannot be amended"
                )
        return amendment

    async def save_simulation(
        self, session_id: UUID, revision_number: int, simulation: PlanSimulation
    ) -> None:
        """Replace a plan revision's stored simulation (ADR 0043); the revision is unchanged."""
        async with self._engine.begin() as connection:
            await connection.execute(
                update(plan_revisions)
                .where(
                    plan_revisions.c.session_id == session_id,
                    plan_revisions.c.number == revision_number,
                )
                .values(simulation=simulation.model_dump(mode="json"))
            )

    async def mark_failed(self, session_id: UUID, error: str) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(
                update(planning_sessions)
                .where(planning_sessions.c.id == session_id)
                .values(status=SessionStatus.FAILED.value, error=error, updated_at=func.now())
            )

    async def fail_interrupted(self) -> int:
        """Fail every session still `planning`: its background task died with the old process."""
        async with self._engine.begin() as connection:
            result = await connection.execute(
                update(planning_sessions)
                .where(planning_sessions.c.status == SessionStatus.PLANNING.value)
                .values(status=SessionStatus.FAILED.value, error=INTERRUPTED, updated_at=func.now())
            )
        return result.rowcount


def _line_row(
    session_id: UUID, revision_number: int, position: int, planned: PlanRevisionLine
) -> dict[str, object]:
    line = planned.line
    return {
        "session_id": session_id,
        "revision_number": revision_number,
        "position": position,
        "sku_id": line.sku_id,
        "region": line.region.value,
        "mechanism": line.mechanism.value,
        "depth_pct": line.depth_pct,
        "duration_weeks": line.duration_weeks,
        "start_week": line.start_week,
        "target_segment": line.target_segment.value,
        "bundle_partner_sku_id": line.bundle_partner_sku_id,
        "expected_units": planned.expected_units,
        "promo_cost": planned.promo_cost,
        "expected_incremental_profit": planned.expected_incremental_profit,
        "why_chosen": None
        if planned.why_chosen is None
        else planned.why_chosen.model_dump(mode="json"),
        "mechanism_comparison": _COMPARISON.dump_python(planned.mechanism_comparison, mode="json"),
        "baseline_units": planned.baseline_units,
        "uplift_pct": planned.uplift_pct,
        "segments": _SEGMENTS.dump_python(planned.segments, mode="json"),
        "cross_effects": _CROSS_EFFECTS.dump_python(planned.cross_effects, mode="json"),
    }


def _revision(row: object, lines: tuple[PlanRevisionLine, ...]) -> PlanRevision:
    values = dict(row._mapping)  # type: ignore[attr-defined]
    status = values["solver_status"]
    return PlanRevision(
        number=values["number"],
        lines=lines,
        solver_status=None if status is None else SolveStatus(status),
        objective=values["objective"],
        binding_constraints=_BINDING.validate_python(values["binding_constraints"] or ()),
        not_selected=_NOT_SELECTED.validate_python(values["not_selected"] or ()),
        simulation=None
        if values["simulation"] is None
        else PlanSimulation.model_validate(values["simulation"]),
        clearance_shortfalls=_SHORTFALLS.validate_python(values["clearance_shortfalls"] or ()),
        policy_findings=_FINDINGS.validate_python(values["policy_findings"] or ()),
        relaxation=None
        if values["relaxation"] is None
        else Relaxation.model_validate(values["relaxation"]),
        open_issues=_ISSUES.validate_python(values["open_issues"] or ()),
        explanation=None
        if values["explanation"] is None
        else PlanExplanation.model_validate(values["explanation"]),
        diff=None if values["diff"] is None else RevisionDiff.model_validate(values["diff"]),
    )


def _revision_line(row: object) -> PlanRevisionLine:
    values = dict(row)  # type: ignore[call-overload]
    line_fields = set(PlanLine.model_fields)
    return PlanRevisionLine(
        line=PlanLine.model_validate({k: v for k, v in values.items() if k in line_fields}),
        expected_units=values["expected_units"],
        promo_cost=values["promo_cost"],
        expected_incremental_profit=values["expected_incremental_profit"],
        why_chosen=None
        if values["why_chosen"] is None
        else WhyChosen.model_validate(values["why_chosen"]),
        mechanism_comparison=_COMPARISON.validate_python(values["mechanism_comparison"] or ()),
        baseline_units=values["baseline_units"],
        uplift_pct=values["uplift_pct"],
        segments=_SEGMENTS.validate_python(values["segments"] or ()),
        cross_effects=_CROSS_EFFECTS.validate_python(values["cross_effects"] or ()),
    )
