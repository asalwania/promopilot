"""A session service that is never used: for app tests that do not touch sessions."""

from sqlalchemy.ext.asyncio import create_async_engine

from promopilot.api.sessions import SessionService
from promopilot.data import RetailData, SessionStore
from promopilot.domain import PlanningRequest, PlanRevision
from promopilot.llm import FakeProvider


class NoModel:
    """A model registry with nothing loaded."""

    async def is_loaded(self) -> bool:
        return False


class NoPlanner:
    """A planner that must never be asked to plan."""

    async def plan(self, request: PlanningRequest) -> PlanRevision:
        raise AssertionError("an offline app never plans")


def offline_sessions() -> SessionService:
    # Creating an engine does not connect, and ASGITransport runs no lifespan.
    engine = create_async_engine("postgresql+asyncpg://unused@127.0.0.1:1/unused")
    return SessionService(
        store=SessionStore(engine),
        data=RetailData(engine),
        llm=FakeProvider([]),
        planner=NoPlanner(),
    )
