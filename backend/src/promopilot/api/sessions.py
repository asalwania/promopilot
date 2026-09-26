"""Planning sessions over HTTP: start one from a brief, then read its state (SPEC §10, ADR 0001).

`POST /api/sessions` returns at once; planning runs as a background task in this process.
"""

import asyncio
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, status

from promopilot.agents import BriefError, PlanningData, plan_session
from promopilot.api.schemas import CreateSessionRequest, SessionCreated, SessionResponse
from promopilot.data import SessionStore
from promopilot.domain import CompanyPolicy
from promopilot.llm import LLMError, LLMProvider

log = structlog.get_logger(__name__)


class SessionService:
    """Owns the planning sessions of one API process and their background tasks."""

    def __init__(
        self,
        *,
        store: SessionStore,
        data: PlanningData,
        llm: LLMProvider,
        policy: CompanyPolicy | None = None,
    ) -> None:
        self._store = store
        self._data = data
        self._llm = llm
        self._policy = policy
        self._tasks: set[asyncio.Task[None]] = set()

    async def start(self, brief: str) -> UUID:
        session_id = await self._store.create(brief)
        task = asyncio.create_task(self._run(session_id, brief))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return session_id

    async def get(self, session_id: UUID) -> SessionResponse | None:
        session = await self._store.get(session_id)
        return None if session is None else SessionResponse.of(session)

    async def recover_interrupted(self) -> None:
        """At startup: sessions left `planning` by a previous process can never finish."""
        failed = await self._store.fail_interrupted()
        if failed:
            log.warning("sessions.interrupted", failed=failed)

    async def close(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _run(self, session_id: UUID, brief: str) -> None:
        try:
            result = await plan_session(brief, self._llm, self._data, policy=self._policy)
        except BriefError as error:
            await self._store.mark_failed(session_id, f"The brief could not be planned: {error}")
        except LLMError as error:
            await self._store.mark_failed(session_id, f"The language model failed: {error}")
        except Exception:
            log.exception("sessions.planning_failed", session_id=str(session_id))
            await self._store.mark_failed(session_id, "Planning failed unexpectedly.")
        else:
            await self._store.save_plan(session_id, result.request, result.revision)


def sessions_router(sessions: SessionService) -> APIRouter:
    router = APIRouter(prefix="/api/sessions", tags=["sessions"])

    @router.post("", status_code=status.HTTP_202_ACCEPTED)
    async def create_session(body: CreateSessionRequest) -> SessionCreated:
        return SessionCreated(session_id=await sessions.start(body.brief))

    @router.get("/{session_id}", responses={404: {"description": "Unknown session"}})
    async def get_session(session_id: UUID) -> SessionResponse:
        found = await sessions.get(session_id)
        if found is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown session")
        return found

    return router
