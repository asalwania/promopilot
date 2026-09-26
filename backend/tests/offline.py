"""A session service that is never used: for app tests that do not touch sessions."""

from sqlalchemy.ext.asyncio import create_async_engine

from promopilot.api.sessions import SessionService
from promopilot.data import RetailData, SessionStore
from promopilot.llm import FakeProvider


def offline_sessions() -> SessionService:
    # Creating an engine does not connect, and ASGITransport runs no lifespan.
    engine = create_async_engine("postgresql+asyncpg://unused@127.0.0.1:1/unused")
    return SessionService(store=SessionStore(engine), data=RetailData(engine), llm=FakeProvider([]))
