"""Load the generated Parquet tables into Postgres: migrate, truncate, COPY (idempotent)."""

from pathlib import Path

import pyarrow.parquet as pq
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from promopilot.data.schema import DATA_TABLES

GENERATED_DIR = "generated"


def alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", "promopilot.data:migrations")
    return config


async def migrate(engine: AsyncEngine) -> None:
    """Bring the schema to the latest migration."""

    def upgrade(connection: Connection) -> None:
        config = alembic_config()
        config.attributes["connection"] = connection
        command.upgrade(config, "head")

    async with engine.begin() as connection:
        await connection.run_sync(upgrade)


async def load_dataset(data_dir: Path, database_url: str) -> dict[str, int]:
    """Replace the data tables with `data_dir/generated/*.parquet`, in one transaction.

    Reloading the same files leaves the same rows. Returns the row count per table.
    """
    engine = create_async_engine(database_url)
    try:
        await migrate(engine)
        counts = {}
        async with engine.begin() as connection:
            names = ", ".join(table.name for table in DATA_TABLES)
            await connection.execute(text(f"TRUNCATE {names} CASCADE"))
            raw = await connection.get_raw_connection()
            driver = raw.driver_connection
            assert driver is not None
            for table in DATA_TABLES:
                parquet = pq.read_table(data_dir / GENERATED_DIR / f"{table.name}.parquet")
                columns = [column.name for column in table.columns]
                values = [parquet.column(name).to_pylist() for name in columns]
                records = list(zip(*values, strict=True))
                await driver.copy_records_to_table(table.name, records=records, columns=columns)
                counts[table.name] = len(records)
        return counts
    finally:
        await engine.dispose()
