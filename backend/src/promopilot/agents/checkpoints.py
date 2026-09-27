"""Where the agent graph keeps its checkpoints (ADR 0046).

`PostgresCheckpoints` is LangGraph's Postgres checkpointer on the app database. It speaks
psycopg 3, not asyncpg, through its own small pool. Its tables are LangGraph's: `setup()` creates
and migrates them when it opens, outside Alembic. psycopg's async mode cannot run on Windows'
Proactor event loop, so a native Windows run needs a selector loop (uvicorn's `--reload`
uses one). `MemoryCheckpoints` keeps them in the process, for tests and the OpenAPI export.
"""

from typing import Any, Protocol

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy.engine import make_url

from promopilot.agents.graph import checkpoint_serializer

POOL_SIZE = 4


class Checkpoints(Protocol):
    async def open(self) -> BaseCheckpointSaver[Any]:
        """The checkpointer, ready to use; called once, inside the running event loop."""
        ...

    async def close(self) -> None: ...


class PostgresCheckpoints:
    def __init__(self, database_url: str) -> None:
        # The app's URL names SQLAlchemy's asyncpg driver; psycopg takes a plain libpq URL.
        self._conninfo = make_url(database_url).set(drivername="postgresql").render_as_string(False)
        self._pool: AsyncConnectionPool[Any] | None = None

    async def open(self) -> BaseCheckpointSaver[Any]:
        pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
            self._conninfo,
            min_size=1,
            max_size=POOL_SIZE,
            open=False,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        )
        await pool.open()
        self._pool = pool
        saver = AsyncPostgresSaver(pool, serde=checkpoint_serializer())
        await saver.setup()
        return saver

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None


class MemoryCheckpoints:
    """Checkpoints that live as long as the process: nothing survives a restart."""

    async def open(self) -> BaseCheckpointSaver[Any]:
        return InMemorySaver(serde=checkpoint_serializer())

    async def close(self) -> None:
        return None
