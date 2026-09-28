"""Persistence for planning sessions' trace events (E8 #45, ADR 0047).

`TraceStore` is the agent graph's trace sink: each event is numbered 1, 2, ... within its
session, in the order appended. Appends to one session take its row lock, so concurrent appends
still get consecutive numbers. `read` returns the session's status and the events after an id,
which is what the SSE stream polls.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from promopilot.data.schema import planning_sessions, trace_events
from promopilot.domain import SessionStatus, SessionUsage, TokensUsed, TraceEvent, TracePayload

_PAYLOAD: TypeAdapter[TracePayload] = TypeAdapter(TracePayload)
_TOKENS = TypeAdapter(TokensUsed)

READ_BATCH: Final = 500
"""The most events one `read` returns."""


@dataclass(frozen=True)
class TraceRead:
    """A session's status, read before its events, and its events after an id, in order."""

    status: SessionStatus
    thread_id: str | None
    events: tuple[TraceEvent, ...]


class TraceStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def append(self, session_id: UUID, node: str | None, payload: TracePayload) -> None:
        """Add the session's next event. Raises `LookupError` for an unknown session."""
        async with self._engine.begin() as connection:
            locked = (
                await connection.execute(
                    select(planning_sessions.c.id)
                    .where(planning_sessions.c.id == session_id)
                    .with_for_update()
                )
            ).one_or_none()
            if locked is None:
                raise LookupError(f"no planning session {session_id}")
            last: int = (
                await connection.execute(
                    select(func.coalesce(func.max(trace_events.c.seq), 0)).where(
                        trace_events.c.session_id == session_id
                    )
                )
            ).scalar_one()
            await connection.execute(
                insert(trace_events).values(
                    session_id=session_id,
                    seq=last + 1,
                    node=node,
                    kind=payload.kind,
                    payload=payload.model_dump(mode="json"),
                )
            )

    async def read(
        self, session_id: UUID, *, after: int, limit: int = READ_BATCH
    ) -> TraceRead | None:
        """The session's status, then up to `limit` of its events numbered above `after`; None
        for an unknown session. The status is read first, so once it is final every event
        written before it became final is among, or before, the events returned."""
        async with self._engine.connect() as connection:
            session = (
                await connection.execute(
                    select(planning_sessions.c.status, planning_sessions.c.thread_id).where(
                        planning_sessions.c.id == session_id
                    )
                )
            ).one_or_none()
            if session is None:
                return None
            rows = (
                await connection.execute(
                    select(trace_events)
                    .where(trace_events.c.session_id == session_id, trace_events.c.seq > after)
                    .order_by(trace_events.c.seq)
                    .limit(limit)
                )
            ).all()
        return TraceRead(
            status=SessionStatus(session.status),
            thread_id=session.thread_id,
            events=tuple(
                TraceEvent(
                    id=row.seq,
                    session_id=row.session_id,
                    at=row.created_at,
                    node=row.node,
                    payload=_PAYLOAD.validate_python(row.payload),
                )
                for row in rows
            ),
        )


async def session_usage(connection: AsyncConnection, session_id: UUID) -> SessionUsage:
    """The sums of the session's token-usage events, in the order they were recorded."""
    payloads: Sequence[object] = (
        (
            await connection.execute(
                select(trace_events.c.payload)
                .where(
                    trace_events.c.session_id == session_id,
                    trace_events.c.kind == "token_usage",
                )
                .order_by(trace_events.c.seq)
            )
        )
        .scalars()
        .all()
    )
    calls = input_tokens = output_tokens = 0
    cost_usd = cost_inr = 0.0
    unpriced: list[str] = []
    for payload in payloads:
        used = _TOKENS.validate_python(payload)
        calls += 1
        input_tokens += used.input_tokens
        output_tokens += used.output_tokens
        if used.cost_usd is None or used.cost_inr is None:
            if used.model not in unpriced:
                unpriced.append(used.model)
            continue
        cost_usd += used.cost_usd
        cost_inr += used.cost_inr
    return SessionUsage(
        calls=calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        cost_inr=cost_inr,
        unpriced_models=tuple(unpriced),
    )
