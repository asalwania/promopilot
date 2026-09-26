"""Alembic environment. Runs on a connection handed over by promopilot.data.migrate,
or standalone (`alembic upgrade head` with DATABASE_URL set)."""

import asyncio

from alembic import context
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from promopilot.config import Settings
from promopilot.data.schema import metadata

config = context.config


def run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_standalone() -> None:
    engine = create_async_engine(Settings().database_url)
    async with engine.connect() as connection:
        await connection.run_sync(run)
        await connection.commit()
    await engine.dispose()


handed_over = config.attributes.get("connection")
if handed_over is not None:
    run(handed_over)
else:
    asyncio.run(run_standalone())
