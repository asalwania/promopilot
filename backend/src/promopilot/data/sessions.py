"""Persistence for planning sessions and their plan revisions (E3; E8 adds trace and approvals)."""

from uuid import UUID, uuid4

from pydantic import TypeAdapter
from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from promopilot.data.schema import plan_lines, plan_revisions, planning_sessions
from promopilot.domain import (
    BindingConstraint,
    ClearanceShortfall,
    MechanismOutcome,
    NotSelectedOption,
    PlanLine,
    PlanningRequest,
    PlanningSession,
    PlanRevision,
    PlanRevisionLine,
    PlanSimulation,
    PolicyFinding,
    SessionStatus,
    SolveStatus,
    WhyChosen,
)

_BINDING = TypeAdapter(tuple[BindingConstraint, ...])
_NOT_SELECTED = TypeAdapter(tuple[NotSelectedOption, ...])
_COMPARISON = TypeAdapter(tuple[MechanismOutcome, ...])
_SHORTFALLS = TypeAdapter(tuple[ClearanceShortfall, ...])
_FINDINGS = TypeAdapter(tuple[PolicyFinding, ...])

INTERRUPTED = "planning was interrupted by an API restart; start a new session"


class SessionStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def create(self, brief: str) -> UUID:
        session_id = uuid4()
        async with self._engine.begin() as connection:
            await connection.execute(
                insert(planning_sessions).values(
                    id=session_id, brief=brief, status=SessionStatus.PLANNING.value
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
        )

    async def save_plan(
        self, session_id: UUID, request: PlanningRequest, revision: PlanRevision
    ) -> None:
        """Store the planning request and the plan revision; the session awaits approval."""
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
                .values(
                    status=SessionStatus.AWAITING_APPROVAL.value,
                    planning_request=request.model_dump(mode="json"),
                    updated_at=func.now(),
                )
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
