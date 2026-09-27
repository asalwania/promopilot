"""Planning sessions over HTTP (SPEC §10, ADR 0001, ADR 0046).

`POST /api/sessions` returns at once. A background task in this process runs the session's
agent graph until the Approval interrupt: the brief is read into a planning request, the
optimising planner plans it (ADR 0038), the Critic validates it and the Explainer explains it.
`POST /approve` and `POST /reject` resume the graph from its checkpoint within the request, so
a decision survives an API restart between planning and deciding.
"""

import asyncio
import weakref
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, status

from promopilot.agents import (
    BriefError,
    Checkpoints,
    GraphTools,
    PlanningError,
    PlanningGraph,
    build_graph,
    graph_state,
    resume_with_decision,
    start_planning,
)
from promopilot.api.schemas import (
    ApproveRequest,
    CreateSessionRequest,
    RejectRequest,
    SessionCreated,
    SessionResponse,
)
from promopilot.data import SessionConflictError, SessionStore
from promopilot.domain import DecisionKind, SessionStatus, SolveStatus
from promopilot.llm import LLMError, LLMProvider

log = structlog.get_logger(__name__)


class SessionNotFoundError(Exception):
    """No planning session has this id."""


class PlanningUnavailableError(Exception):
    """The agent graph's checkpointer could not be opened, so nothing can be planned."""


class SessionService:
    """Owns the planning sessions of one API process: their agent graph and its background
    runs, and the decisions that resume it."""

    def __init__(
        self,
        *,
        store: SessionStore,
        tools: GraphTools,
        llm: LLMProvider,
        checkpoints: Checkpoints,
    ) -> None:
        self._store = store
        self._tools = tools
        self._llm = llm
        self._checkpoints = checkpoints
        self._graph: PlanningGraph | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        # One decision at a time per session, so two requests cannot both resume one interrupt.
        self._locks: weakref.WeakValueDictionary[UUID, asyncio.Lock] = weakref.WeakValueDictionary()

    async def open(self) -> None:
        """Open the checkpointer and build the agent graph on it (at startup)."""
        self._graph = build_graph(self._tools, self._llm, await self._checkpoints.open())

    async def start(self, brief: str) -> UUID:
        graph = self._require_graph()
        session_id = await self._store.create(brief)
        task = asyncio.create_task(self._run(graph, session_id, brief))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return session_id

    async def get(self, session_id: UUID) -> SessionResponse | None:
        session = await self._store.get(session_id)
        return None if session is None else SessionResponse.of(session)

    async def approve(self, session_id: UUID, revision_number: int) -> SessionResponse:
        """Approve the latest plan revision; the session is then final. Raises
        `SessionNotFoundError`, or `SessionConflictError` when the session is not awaiting
        approval, the revision is not its latest, or the revision is infeasible."""
        return await self._decide(session_id, DecisionKind.APPROVED, revision_number, None)

    async def reject(self, session_id: UUID, revision_number: int, reason: str) -> SessionResponse:
        """Reject the latest plan revision with a reason; the session stays open for an
        amendment. Raises like `approve`."""
        return await self._decide(session_id, DecisionKind.REJECTED, revision_number, reason)

    async def recover_interrupted(self) -> None:
        """At startup: sessions left `planning` by a previous process can never finish.

        Only a session paused at an interrupt resumes from its checkpoint (ADR 0046).
        """
        failed = await self._store.fail_interrupted()
        if failed:
            log.warning("sessions.interrupted", failed=failed)

    async def close(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self._checkpoints.close()

    def _require_graph(self) -> PlanningGraph:
        if self._graph is None:
            raise PlanningUnavailableError(
                "planning is unavailable: the agent graph's checkpoints could not be opened"
            )
        return self._graph

    async def _decide(
        self, session_id: UUID, decision: DecisionKind, revision_number: int, reason: str | None
    ) -> SessionResponse:
        graph = self._require_graph()
        lock = self._locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            session = await self._store.get(session_id)
            if session is None:
                raise SessionNotFoundError(str(session_id))
            verb = "approved" if decision is DecisionKind.APPROVED else "rejected"
            if session.status is not SessionStatus.AWAITING_APPROVAL:
                raise SessionConflictError(
                    f"the session is {session.status.value}: only a session awaiting approval "
                    f"can be {verb}"
                )
            latest = session.latest_revision
            if latest is None or latest.number != revision_number:
                raise SessionConflictError(
                    f"plan revision {revision_number} is not the session's latest plan revision"
                )
            if decision is DecisionKind.APPROVED and latest.solver_status is SolveStatus.INFEASIBLE:
                raise SessionConflictError(
                    f"plan revision {revision_number} is infeasible: amend the brief with its "
                    "relaxation before approving"
                )
            thread_id = session.thread_id
            paused = None if thread_id is None else await graph_state(graph, thread_id)
            if thread_id is None or paused is None or not paused.awaits_decision:
                raise SessionConflictError(
                    "the session's agent graph is not waiting for a decision"
                )
            await resume_with_decision(
                graph, thread_id, decision, revision_number=revision_number, reason=reason
            )
            decided = await self._store.get(session_id)
        if decided is None:
            raise SessionNotFoundError(str(session_id))
        return SessionResponse.of(decided)

    async def _run(self, graph: PlanningGraph, session_id: UUID, brief: str) -> None:
        try:
            await start_planning(graph, str(session_id), session_id, brief)
            # Only once the Approval interrupt is checkpointed can anyone decide on it.
            paused = await graph_state(graph, str(session_id))
            if paused is not None and paused.awaits_decision:
                await self._store.await_approval(session_id)
        except BriefError as error:
            await self._store.mark_failed(session_id, f"The brief could not be planned: {error}")
        except PlanningError as error:
            await self._store.mark_failed(session_id, f"Planning is not possible yet: {error}")
        except LLMError as error:
            await self._store.mark_failed(session_id, f"The language model failed: {error}")
        except Exception:
            log.exception("sessions.planning_failed", session_id=str(session_id))
            await self._store.mark_failed(session_id, "Planning failed unexpectedly.")


def sessions_router(sessions: SessionService) -> APIRouter:
    router = APIRouter(prefix="/api/sessions", tags=["sessions"])
    decision_responses: dict[int | str, dict[str, object]] = {
        status.HTTP_404_NOT_FOUND: {"description": "Unknown session"},
        status.HTTP_409_CONFLICT: {
            "description": "The session is not awaiting approval, the revision is not its "
            "latest, or (approve) the revision is infeasible"
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Planning is unavailable"},
    }

    @router.post(
        "",
        status_code=status.HTTP_202_ACCEPTED,
        responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Planning is unavailable"}},
    )
    async def create_session(body: CreateSessionRequest) -> SessionCreated:
        try:
            return SessionCreated(session_id=await sessions.start(body.brief))
        except PlanningUnavailableError as error:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error

    @router.get("/{session_id}", responses={404: {"description": "Unknown session"}})
    async def get_session(session_id: UUID) -> SessionResponse:
        found = await sessions.get(session_id)
        if found is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown session")
        return found

    @router.post("/{session_id}/approve", responses=decision_responses)
    async def approve_session(session_id: UUID, body: ApproveRequest) -> SessionResponse:
        """Approve the session's latest plan revision, which makes it final (SF-04)."""
        try:
            return await sessions.approve(session_id, body.revision_number)
        except SessionNotFoundError as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown session") from error
        except SessionConflictError as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
        except PlanningUnavailableError as error:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error

    @router.post("/{session_id}/reject", responses=decision_responses)
    async def reject_session(session_id: UUID, body: RejectRequest) -> SessionResponse:
        """Reject the session's latest plan revision with a reason; the session stays open."""
        try:
            return await sessions.reject(session_id, body.revision_number, body.reason)
        except SessionNotFoundError as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown session") from error
        except SessionConflictError as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
        except PlanningUnavailableError as error:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error

    return router
