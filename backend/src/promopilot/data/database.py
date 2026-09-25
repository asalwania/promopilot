"""Async Postgres engine and connectivity probe."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


class PostgresDatabaseProbe:
    """Reports whether Postgres answers a trivial query."""

    def __init__(self, database_url: str, *, timeout_seconds: float = 2.0) -> None:
        self._engine = create_async_engine(
            database_url,
            pool_pre_ping=True,
            connect_args={"timeout": timeout_seconds},
        )

    async def is_healthy(self) -> bool:
        try:
            async with self._engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except Exception:
            return False
        return True

    async def dispose(self) -> None:
        await self._engine.dispose()
