from collections.abc import Iterator

import pytest
from httpx import ASGITransport, AsyncClient
from testcontainers.community.postgres import PostgresContainer

from promopilot.api.main import create_app
from promopilot.data.database import PostgresDatabaseProbe

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def postgres_url() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as postgres:
        yield postgres.get_connection_url()


async def get_database_check(database_url: str) -> str:
    probe = PostgresDatabaseProbe(database_url)
    try:
        app = create_app(database_probe=probe)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")
        return str(response.json()["checks"]["database"])
    finally:
        await probe.dispose()


async def test_health_reports_database_ok_against_real_postgres(postgres_url: str) -> None:
    assert await get_database_check(postgres_url) == "ok"


async def test_health_reports_database_error_when_postgres_is_unreachable() -> None:
    unreachable = "postgresql+asyncpg://promopilot:promopilot@127.0.0.1:1/promopilot"
    assert await get_database_check(unreachable) == "error"
