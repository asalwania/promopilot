from httpx import ASGITransport, AsyncClient

from promopilot.api.main import create_app


class FakeDatabaseProbe:
    def __init__(self, *, healthy: bool) -> None:
        self.healthy = healthy

    async def is_healthy(self) -> bool:
        return self.healthy


async def get_health(probe: FakeDatabaseProbe) -> tuple[int, dict[str, object]]:
    app = create_app(database_probe=probe)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    return response.status_code, response.json()


async def test_health_reports_ok_when_database_is_reachable() -> None:
    status_code, body = await get_health(FakeDatabaseProbe(healthy=True))

    assert status_code == 200
    assert body == {
        "status": "ok",
        "version": "0.1.0",
        "checks": {"database": "ok", "model_registry": "not_initialised"},
    }


async def test_health_is_degraded_but_alive_when_database_is_unreachable() -> None:
    status_code, body = await get_health(FakeDatabaseProbe(healthy=False))

    assert status_code == 200
    assert body["status"] == "degraded"
    assert body["checks"] == {"database": "error", "model_registry": "not_initialised"}


class ExplodingDatabaseProbe:
    async def is_healthy(self) -> bool:
        raise ConnectionError("database went away")


async def test_health_is_degraded_when_database_probe_raises() -> None:
    app = create_app(database_probe=ExplodingDatabaseProbe())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["checks"]["database"] == "error"


async def test_health_is_also_served_under_the_api_prefix_for_the_web_proxy() -> None:
    app = create_app(database_probe=FakeDatabaseProbe(healthy=True))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
