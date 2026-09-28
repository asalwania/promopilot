"""Trace events in Postgres (#45, ADR 0047): numbered per session in the order appended, read
back after any id, and summed into the session's usage."""

import asyncio
from collections.abc import AsyncIterator, Iterator
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from promopilot.data import SessionStore, TraceStore, migrate
from promopilot.domain import (
    DecisionMade,
    NodeFinished,
    NodeOutcome,
    NodeStarted,
    SessionStatus,
    SessionUsage,
    TokensUsed,
)

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def postgres_url() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as postgres:
        yield postgres.get_connection_url()


@pytest.fixture
async def engine(postgres_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(postgres_url)
    await migrate(engine)
    yield engine
    await engine.dispose()


async def test_events_are_numbered_per_session_and_read_back_after_an_id(
    engine: AsyncEngine,
) -> None:
    sessions, trace = SessionStore(engine), TraceStore(engine)
    first, second = await sessions.create("brief one"), await sessions.create("brief two")

    await trace.append(first, "context", NodeStarted())
    await trace.append(second, "context", NodeStarted())
    await trace.append(first, "context", DecisionMade(decision="d", summary="Decided."))
    await trace.append(
        first, "context", NodeFinished(outcome=NodeOutcome.COMPLETED, duration_ms=12)
    )

    read = await trace.read(first, after=0)
    assert read is not None
    assert read.status is SessionStatus.PLANNING
    assert read.thread_id == str(first)
    assert [(e.id, e.session_id, e.node, e.payload.kind) for e in read.events] == [
        (1, first, "context", "node_started"),
        (2, first, "context", "decision"),
        (3, first, "context", "node_finished"),
    ]
    resumed = await trace.read(first, after=1)
    assert resumed is not None
    assert [e.id for e in resumed.events] == [2, 3]
    assert resumed.events == read.events[1:]
    other = await trace.read(second, after=0)
    assert other is not None
    assert [e.id for e in other.events] == [1]


async def test_reading_an_unknown_session_is_none(engine: AsyncEngine) -> None:
    assert await TraceStore(engine).read(uuid4(), after=0) is None


async def test_concurrent_appends_to_one_session_get_distinct_consecutive_ids(
    engine: AsyncEngine,
) -> None:
    sessions, trace = SessionStore(engine), TraceStore(engine)
    session_id = await sessions.create("brief")

    await asyncio.gather(*(trace.append(session_id, "planner", NodeStarted()) for _ in range(10)))

    read = await trace.read(session_id, after=0)
    assert read is not None
    assert [e.id for e in read.events] == list(range(1, 11))


async def test_the_sessions_usage_sums_its_token_usage_events(engine: AsyncEngine) -> None:
    sessions, trace = SessionStore(engine), TraceStore(engine)
    session_id = await sessions.create("brief")
    fresh = await sessions.get(session_id)
    assert fresh is not None
    assert fresh.usage == SessionUsage()

    await trace.append(
        session_id,
        "context",
        TokensUsed(
            model="gpt-4.1-mini",
            input_tokens=1_000,
            output_tokens=500,
            cost_usd=0.0012,
            cost_inr=0.1152,
        ),
    )
    await trace.append(session_id, "context", NodeStarted())
    await trace.append(
        session_id,
        "planner",
        TokensUsed(
            model="claude-sonnet-5",
            input_tokens=100,
            output_tokens=10,
            cost_usd=0.0003,
            cost_inr=0.0288,
        ),
    )
    await trace.append(
        session_id,
        "planner",
        TokensUsed(model="mystery", input_tokens=7, output_tokens=3, cost_usd=None, cost_inr=None),
    )

    session = await sessions.get(session_id)
    assert session is not None
    usage = session.usage
    assert (usage.calls, usage.input_tokens, usage.output_tokens) == (3, 1_107, 513)
    assert usage.cost_usd == pytest.approx(0.0015)
    assert usage.cost_inr == pytest.approx(0.144)
    assert usage.unpriced_models == ("mystery",)
