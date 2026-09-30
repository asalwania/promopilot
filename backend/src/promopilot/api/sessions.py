"""Planning sessions over HTTP (SPEC §10, ADR 0001, ADR 0046).

`POST /api/sessions` returns at once. A background task in this process runs the session's
agent graph until the Approval interrupt: the brief is read into a planning request, the
optimising planner plans it (ADR 0038), the Critic validates it and the Explainer explains it.
`POST /approve` and `POST /reject` resume the graph from its checkpoint within the request, so
a decision survives an API restart between planning and deciding. When the Context agent asks
questions the graph pauses at Clarify instead; `POST /clarify` keeps the answers and resumes it
in the background, since planning follows (ADR 0048). `POST /amend` keeps an amendment of a
session awaiting approval, or rejected, and resumes the graph from Approval in the background:
the Context agent reads the request again and a new plan revision is planned, with its diff
from the previous one (ADR 0052).

Every step the graph takes is a trace event in Postgres (ADR 0047). `GET /events` streams them
over SSE: it replays the events after `Last-Event-ID`, then polls for new ones until the
session is final, and ends with an `end` event.

A background run that has not paused within `SESSION_TIMEOUT_SECONDS` is cancelled: the
session fails with the reason, after a `session_timed_out` decision in its trace (ADR 0071).
"""

import asyncio
import weakref
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable, Mapping
from typing import Annotated, Protocol, cast
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.sse import EventSourceResponse, ServerSentEvent

from promopilot.agents import (
    BriefError,
    Checkpoints,
    GraphTools,
    PlanningError,
    PlanningGraph,
    acceptable_relaxation,
    approval_refusal,
    build_graph,
    graph_state,
    relaxation_amendment,
    resume_with_acceptance,
    resume_with_amendment,
    resume_with_answers,
    resume_with_decision,
    start_planning,
)
from promopilot.api.demo import DemoRecordings
from promopilot.api.rate_limit import (
    TOO_MANY_REQUESTS,
    RateLimiter,
    RateLimitGroup,
    rate_limited,
)
from promopilot.api.schemas import (
    AmendRequest,
    ApproveRequest,
    ClarifyRequest,
    CreateSessionRequest,
    RejectRequest,
    SessionCreated,
    SessionResponse,
    TraceStreamEnd,
)
from promopilot.data import AMENDABLE, SessionConflictError, SessionStore, TraceRead
from promopilot.domain import (
    Clarification,
    DecisionKind,
    DecisionMade,
    PlanningSession,
    SessionStatus,
    TraceEvent,
)
from promopilot.llm import LLMError, LLMProvider

log = structlog.get_logger(__name__)


class SessionNotFoundError(Exception):
    """No planning session has this id."""


class PlanningUnavailableError(Exception):
    """The agent graph's checkpointer could not be opened, so nothing can be planned."""


class ClarificationAnswersError(Exception):
    """The answers do not match the open questions one for one: the API's 422."""


class TraceReader(Protocol):
    """Reads a session's trace events (`promopilot.data.TraceStore`)."""

    async def read(self, session_id: UUID, *, after: int) -> TraceRead | None: ...


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
        trace: TraceReader,
        trace_poll_interval_s: float = 0.5,
        session_timeout_s: float = 900.0,
        recordings: DemoRecordings | None = None,
    ) -> None:
        if session_timeout_s <= 0:
            raise ValueError("session_timeout_s must be positive")
        self._store = store
        self._tools = tools
        self._llm = llm
        self._checkpoints = checkpoints
        self._trace = trace
        self._poll_interval_s = trace_poll_interval_s
        self._timeout_s = session_timeout_s
        # Replaying: whether each session stays on the demo recordings (ADR 0073).
        self._recordings = recordings
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
        # The run inherits the session id, and the request's, on every line (ADR 0085).
        with structlog.contextvars.bound_contextvars(session_id=str(session_id)):
            log.info("sessions.created", brief_chars=len(brief))
            log.debug("sessions.brief", brief=brief)
            self._spawn(
                self._drive(
                    graph,
                    session_id,
                    lambda: start_planning(graph, str(session_id), session_id, brief),
                )
            )
        return session_id

    async def get(self, session_id: UUID) -> SessionResponse | None:
        session = await self._store.get(session_id)
        return None if session is None else self._response(session)

    async def exists(self, session_id: UUID) -> bool:
        return await self._trace.read(session_id, after=0) is not None

    async def events(
        self, session_id: UUID, *, after: int
    ) -> AsyncIterator[TraceEvent | SessionStatus]:
        """The session's trace events numbered above `after`, in order, as they are written;
        then, once the session is final and no more can come, its final status.

        A session is final when it failed, or was approved and its graph has run to the end;
        a session planned before E8 has no graph and never gets more events. Raises
        `SessionNotFoundError` for an unknown session.
        """
        last = after
        ending = False
        while True:
            read = await self._trace.read(session_id, after=last)
            if read is None:
                raise SessionNotFoundError(str(session_id))
            for event in read.events:
                yield event
                last = event.id
            if read.events:
                continue
            if ending:
                yield read.status
                return
            # Once final, every event is written: one more read picks up any this one missed.
            ending = await self._is_final(read)
            if not ending:
                await asyncio.sleep(self._poll_interval_s)

    async def approve(self, session_id: UUID, revision_number: int) -> SessionResponse:
        """Approve the latest plan revision; the session is then final. Raises
        `SessionNotFoundError`, or `SessionConflictError` when the session is not awaiting
        approval, the revision is not its latest, or the revision is infeasible."""
        return await self._decide(session_id, DecisionKind.APPROVED, revision_number, None)

    async def reject(self, session_id: UUID, revision_number: int, reason: str) -> SessionResponse:
        """Reject the latest plan revision with a reason; the session stays open for an
        amendment. Raises like `approve`."""
        return await self._decide(session_id, DecisionKind.REJECTED, revision_number, reason)

    async def clarify(self, session_id: UUID, answers: Mapping[str, str]) -> SessionResponse:
        """Answer every open clarification question; the session is `planning` again and the
        graph resumes from its checkpoint in the background. Raises `SessionNotFoundError`,
        `SessionConflictError` when the session is not awaiting clarification, or
        `ClarificationAnswersError` when the answers do not match the open questions."""
        graph = self._require_graph()
        lock = self._locks.setdefault(session_id, asyncio.Lock())
        with structlog.contextvars.bound_contextvars(session_id=str(session_id)):
            async with lock:
                session = await self._store.get(session_id)
                if session is None:
                    raise SessionNotFoundError(str(session_id))
                if session.status is not SessionStatus.AWAITING_CLARIFICATION:
                    raise SessionConflictError(
                        f"the session is {session.status.value}: only a session awaiting "
                        "clarification can be answered"
                    )
                thread_id = session.thread_id
                paused = None if thread_id is None else await graph_state(graph, thread_id)
                if thread_id is None or paused is None or not paused.awaits_clarification:
                    raise SessionConflictError(
                        "the session's agent graph is not waiting for clarification"
                    )
                questions = paused.values.questions
                asked = {question.id for question in questions}
                missing, unknown = sorted(asked - set(answers)), sorted(set(answers) - asked)
                if missing or unknown:
                    raise ClarificationAnswersError(
                        "answer every open question by its id"
                        + (f"; unanswered: {', '.join(missing)}" if missing else "")
                        + (f"; not asked: {', '.join(unknown)}" if unknown else "")
                    )
                answered = tuple(
                    Clarification(question=question, answer=answers[question.id])
                    for question in questions
                )
                await self._store.answer_clarifications(
                    session_id, session.clarifications + answered
                )
                log.info("sessions.clarified", answer_count=len(answered))
                log.debug("sessions.answers", answers=dict(answers))
                self._spawn(
                    self._drive(
                        graph, session_id, lambda: resume_with_answers(graph, thread_id, answers)
                    )
                )
                resumed = await self._store.get(session_id)
        if resumed is None:
            raise SessionNotFoundError(str(session_id))
        return self._response(resumed)

    async def amend(
        self, session_id: UUID, text: str | None, *, accept_relaxation: bool = False
    ) -> SessionResponse:
        """Amend the planning request of a session awaiting approval, or rejected, in the
        manager's words or by accepting the latest revision's relaxation; the session is
        `planning` again and the graph resumes from Approval in the background (ADR 0052).
        Raises `SessionNotFoundError`, or `SessionConflictError` when the session is in another
        status, or there is no relaxation to accept."""
        graph = self._require_graph()
        lock = self._locks.setdefault(session_id, asyncio.Lock())
        with structlog.contextvars.bound_contextvars(session_id=str(session_id)):
            async with lock:
                session = await self._store.get(session_id)
                if session is None:
                    raise SessionNotFoundError(str(session_id))
                if session.status not in AMENDABLE:
                    raise SessionConflictError(
                        f"the session is {session.status.value}: only a session awaiting "
                        "approval, or rejected, can be amended"
                    )
                latest = session.latest_revision
                if latest is None:
                    raise SessionConflictError("the session has no plan revision to amend")
                relaxation = None
                if accept_relaxation:
                    relaxation = acceptable_relaxation(latest)
                    if relaxation is None:
                        raise SessionConflictError(
                            f"plan revision {latest.number} has no relaxation to accept"
                        )
                    text = relaxation_amendment(relaxation)
                if text is None:
                    raise ValueError("an amendment needs text or an accepted relaxation")
                thread_id = session.thread_id
                paused = None if thread_id is None else await graph_state(graph, thread_id)
                if thread_id is None or paused is None or not paused.awaits_decision:
                    raise SessionConflictError(
                        "the session's agent graph is not waiting at approval"
                    )
                await self._store.amend(session_id, text, latest.number, relaxation)
                log.info(
                    "sessions.amended",
                    revision_number=latest.number,
                    accept_relaxation=accept_relaxation,
                    amendment_chars=len(text),
                )
                log.debug("sessions.amendment", amendment=text)
                amendment, accepted = text, relaxation
                self._spawn(
                    self._drive(
                        graph,
                        session_id,
                        # An accepted relaxation is applied in code, not read (ADR 0083).
                        lambda: (
                            resume_with_amendment(graph, thread_id, amendment)
                            if accepted is None
                            else resume_with_acceptance(graph, thread_id, accepted)
                        ),
                    )
                )
                amended = await self._store.get(session_id)
        if amended is None:
            raise SessionNotFoundError(str(session_id))
        return self._response(amended)

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

    async def _is_final(self, read: TraceRead) -> bool:
        if read.status is SessionStatus.FAILED or read.thread_id is None:
            return True
        if read.status is not SessionStatus.APPROVED:
            return False
        # Approval records the decision before its node ends and Done runs; the thread has
        # ended once its last checkpoint has nothing left to run.
        if self._graph is None:
            return True
        ended = await graph_state(self._graph, read.thread_id)
        return ended is None or ended.paused_at == ()

    def _response(self, session: PlanningSession) -> SessionResponse:
        recordings = self._recordings
        return SessionResponse.of(
            session, demo_recording=None if recordings is None else recordings.of(session)
        )

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
        with structlog.contextvars.bound_contextvars(session_id=str(session_id)):
            return await self._decide_locked(
                graph, lock, session_id, decision, revision_number, reason
            )

    async def _decide_locked(
        self,
        graph: PlanningGraph,
        lock: asyncio.Lock,
        session_id: UUID,
        decision: DecisionKind,
        revision_number: int,
        reason: str | None,
    ) -> SessionResponse:
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
            refusal = approval_refusal(latest)
            if decision is DecisionKind.APPROVED and refusal is not None:
                raise SessionConflictError(refusal)
            thread_id = session.thread_id
            paused = None if thread_id is None else await graph_state(graph, thread_id)
            if thread_id is None or paused is None or not paused.awaits_decision:
                raise SessionConflictError(
                    "the session's agent graph is not waiting for a decision"
                )
            log.info("sessions.decided", decision=decision.value, revision_number=revision_number)
            if reason is not None:
                log.debug("sessions.rejection_reason", rejection_reason=reason)
            await resume_with_decision(
                graph, thread_id, decision, revision_number=revision_number, reason=reason
            )
            decided = await self._store.get(session_id)
        if decided is None:
            raise SessionNotFoundError(str(session_id))
        return self._response(decided)

    def _spawn(self, run: Awaitable[None]) -> None:
        task = asyncio.ensure_future(run)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _drive(
        self, graph: PlanningGraph, session_id: UUID, run: Callable[[], Awaitable[list[str]]]
    ) -> None:
        """Run the graph until it pauses or fails, then record where it paused."""
        # The run is its own task, so the session id stays on every log line it writes.
        structlog.contextvars.bind_contextvars(session_id=str(session_id))
        deadline = asyncio.timeout(self._timeout_s)
        try:
            async with deadline:
                await run()
            # Only once an interrupt is checkpointed can anyone answer it.
            paused = await graph_state(graph, str(session_id))
            if paused is not None and paused.awaits_decision:
                await self._store.await_approval(session_id)
            elif paused is not None and paused.awaits_clarification:
                await self._store.await_clarification(session_id, paused.values.questions)
        except BriefError as error:
            await self._store.mark_failed(session_id, f"The brief could not be planned: {error}")
        except PlanningError as error:
            await self._store.mark_failed(session_id, f"Planning is not possible yet: {error}")
        except LLMError as error:
            await self._store.mark_failed(session_id, f"The language model failed: {error}")
        except TimeoutError:
            if not deadline.expired():
                log.exception("sessions.planning_failed", session_id=str(session_id))
                await self._store.mark_failed(session_id, "Planning failed unexpectedly.")
                return
            await self._time_out(session_id)
        except Exception:
            log.exception("sessions.planning_failed", session_id=str(session_id))
            await self._store.mark_failed(session_id, "Planning failed unexpectedly.")

    async def _time_out(self, session_id: UUID) -> None:
        reason = f"Planning took longer than {self._timeout_s:g} s and was stopped."
        log.warning("sessions.timed_out", timeout_s=self._timeout_s)
        await self._tools.trace.append(
            session_id, None, DecisionMade(decision="session_timed_out", summary=reason)
        )
        await self._store.mark_failed(session_id, reason)


def sessions_router(sessions: SessionService, limiter: RateLimiter | None = None) -> APIRouter:
    """The session routes; creating, clarifying and amending a session share the client's
    planning budget when `limiter` is set (ADR 0079)."""
    router = APIRouter(prefix="/api/sessions", tags=["sessions"])
    planning = rate_limited(limiter, RateLimitGroup.PLANNING)
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
        responses={
            status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Planning is unavailable"},
            **TOO_MANY_REQUESTS,
        },
        dependencies=planning,
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

    async def known_session(session_id: UUID) -> UUID:
        if not await sessions.exists(session_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown session")
        return session_id

    @router.get(
        "/{session_id}/events",
        response_class=EventSourceResponse,
        responses={404: {"description": "Unknown session"}},
    )
    async def session_events(
        session_id: Annotated[UUID, Depends(known_session)],
        last_event_id: Annotated[str | None, Header()] = None,
    ) -> AsyncIterable[TraceEvent | TraceStreamEnd]:
        """The session's trace events over SSE (SF-01, ADR 0047), in order, as they happen.

        Each event's SSE `id` is its number in the session; a client that reconnects with
        `Last-Event-ID` gets the events after it, with no gaps or repeats (a missing or
        non-numeric one replays the trace from the start). Once the session is final
        (approved, or failed) the stream sends `event: end` with its status and closes.
        """
        after = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0
        async for item in sessions.events(session_id, after=after):
            if isinstance(item, TraceEvent):
                yield _documented(ServerSentEvent(data=item, id=str(item.id)))
            else:
                end = TraceStreamEnd(session_id=session_id, status=item)
                yield _documented(ServerSentEvent(data=end, event="end"))

    @router.post(
        "/{session_id}/clarify",
        status_code=status.HTTP_202_ACCEPTED,
        responses={
            status.HTTP_404_NOT_FOUND: {"description": "Unknown session"},
            status.HTTP_409_CONFLICT: {"description": "The session is not awaiting clarification"},
            status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Planning is unavailable"},
            **TOO_MANY_REQUESTS,
        },
        dependencies=planning,
    )
    async def clarify_session(session_id: UUID, body: ClarifyRequest) -> SessionResponse:
        """Answer the open clarification questions; planning resumes in the background."""
        try:
            return await sessions.clarify(session_id, body.answers)
        except SessionNotFoundError as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown session") from error
        except SessionConflictError as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
        except ClarificationAnswersError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
        except PlanningUnavailableError as error:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error

    @router.post(
        "/{session_id}/amend",
        status_code=status.HTTP_202_ACCEPTED,
        responses={
            status.HTTP_404_NOT_FOUND: {"description": "Unknown session"},
            status.HTTP_409_CONFLICT: {
                "description": "The session is not awaiting approval or rejected, or "
                "(accept_relaxation) its latest revision has no relaxation"
            },
            status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Planning is unavailable"},
            **TOO_MANY_REQUESTS,
        },
        dependencies=planning,
    )
    async def amend_session(session_id: UUID, body: AmendRequest) -> SessionResponse:
        """Amend the planning request (AG-05); a new plan revision, with its diff from the
        previous one, is planned in the background."""
        try:
            return await sessions.amend(
                session_id, body.text, accept_relaxation=body.accept_relaxation
            )
        except SessionNotFoundError as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown session") from error
        except SessionConflictError as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
        except PlanningUnavailableError as error:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error

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


def _documented(event: ServerSentEvent) -> TraceEvent | TraceStreamEnd:
    """FastAPI documents each SSE event's data from the route's annotation but sends a
    `ServerSentEvent` as it is, with its id and name; this lets it through mypy."""
    return cast(TraceEvent | TraceStreamEnd, event)
