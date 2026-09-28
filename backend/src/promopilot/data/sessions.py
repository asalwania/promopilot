"""Persistence for planning sessions, their plan revisions, their explanations and every
decision on them (E3, E8: ADR 0046, ADR 0050)."""

from uuid import UUID, uuid4

from pydantic import TypeAdapter
from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from promopilot.data.schema import approvals, plan_lines, plan_revisions, planning_sessions
from promopilot.domain import (
    BindingConstraint,
    ClearanceShortfall,
    DecisionKind,
    MechanismOutcome,
    NotSelectedOption,
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
    SessionStatus,
    SolveStatus,
    Violation,
    WhyChosen,
)

_BINDING = TypeAdapter(tuple[BindingConstraint, ...])
_NOT_SELECTED = TypeAdapter(tuple[NotSelectedOption, ...])
_COMPARISON = TypeAdapter(tuple[MechanismOutcome, ...])
_SHORTFALLS = TypeAdapter(tuple[ClearanceShortfall, ...])
_FINDINGS = TypeAdapter(tuple[PolicyFinding, ...])
_ISSUES = TypeAdapter(tuple[Violation, ...])

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
        )

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
        self, session_id: UUID, revision_number: int, issues: tuple[Violation, ...]
    ) -> None:
        """Store the violations the Critic left open on a plan revision."""
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
    )
