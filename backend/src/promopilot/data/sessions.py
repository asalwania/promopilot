"""Persistence for planning sessions and their plan revisions (E3; E8 adds trace and approvals)."""

from uuid import UUID, uuid4

from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from promopilot.data.schema import plan_lines, plan_revisions, planning_sessions
from promopilot.domain import (
    PlanLine,
    PlanningRequest,
    PlanningSession,
    PlanRevision,
    PlanRevisionLine,
    SessionStatus,
)

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
            latest = (
                await connection.execute(
                    select(func.max(plan_revisions.c.number)).where(
                        plan_revisions.c.session_id == session_id
                    )
                )
            ).scalar_one()
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
            if latest is None
            else PlanRevision(number=latest, lines=tuple(_revision_line(row) for row in lines)),
            error=session.error,
        )

    async def save_plan(
        self, session_id: UUID, request: PlanningRequest, revision: PlanRevision
    ) -> None:
        """Store the planning request and the plan revision; the session awaits approval."""
        async with self._engine.begin() as connection:
            await connection.execute(
                insert(plan_revisions).values(session_id=session_id, number=revision.number)
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
    }


def _revision_line(row: object) -> PlanRevisionLine:
    values = dict(row)  # type: ignore[call-overload]
    line_fields = set(PlanLine.model_fields)
    return PlanRevisionLine(
        line=PlanLine.model_validate({k: v for k, v in values.items() if k in line_fields}),
        expected_units=values["expected_units"],
        promo_cost=values["promo_cost"],
        expected_incremental_profit=values["expected_incremental_profit"],
    )
