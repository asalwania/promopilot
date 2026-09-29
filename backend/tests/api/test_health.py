import pytest
from httpx import ASGITransport, AsyncClient

from promopilot.api.main import create_app
from promopilot.api.schemas import LLMStatus
from promopilot.config import Settings
from tests.offline import offline_sessions


class FakeDatabaseProbe:
    def __init__(self, *, healthy: bool) -> None:
        self.healthy = healthy

    async def is_healthy(self) -> bool:
        return self.healthy


class FakeModelStatus:
    def __init__(self, *, loaded: bool) -> None:
        self.loaded = loaded

    async def is_loaded(self) -> bool:
        return self.loaded


async def get_health(
    probe: FakeDatabaseProbe, model: FakeModelStatus | None = None
) -> tuple[int, dict[str, object]]:
    app = create_app(
        database_probe=probe,
        model_status=model or FakeModelStatus(loaded=True),
        sessions=offline_sessions(),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    return response.status_code, response.json()


async def test_health_reports_ok_when_database_is_reachable() -> None:
    status_code, body = await get_health(FakeDatabaseProbe(healthy=True))

    assert status_code == 200
    assert body == {
        "status": "ok",
        "version": "0.1.0",
        "checks": {"database": "ok", "model_registry": "ok"},
        "llm": {"mode": "replay", "provider": "replay", "model": None},
    }


async def test_health_is_degraded_but_alive_when_database_is_unreachable() -> None:
    status_code, body = await get_health(FakeDatabaseProbe(healthy=False))

    assert status_code == 200
    assert body["status"] == "degraded"
    assert body["checks"] == {"database": "error", "model_registry": "ok"}


class ExplodingDatabaseProbe:
    async def is_healthy(self) -> bool:
        raise ConnectionError("database went away")


async def test_health_is_degraded_when_database_probe_raises() -> None:
    app = create_app(
        database_probe=ExplodingDatabaseProbe(),
        model_status=FakeModelStatus(loaded=True),
        sessions=offline_sessions(),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["checks"]["database"] == "error"


async def test_health_is_also_served_under_the_api_prefix_for_the_web_proxy() -> None:
    app = create_app(
        database_probe=FakeDatabaseProbe(healthy=True),
        model_status=FakeModelStatus(loaded=True),
        sessions=offline_sessions(),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_health_is_degraded_when_no_demand_model_is_loaded() -> None:
    status_code, body = await get_health(
        FakeDatabaseProbe(healthy=True), FakeModelStatus(loaded=False)
    )

    assert status_code == 200
    assert body["status"] == "degraded"
    assert body["checks"] == {"database": "ok", "model_registry": "missing"}


class ExplodingModelStatus:
    async def is_loaded(self) -> bool:
        raise ConnectionError("registry went away")


async def test_health_reports_the_model_missing_when_the_registry_check_raises() -> None:
    app = create_app(
        database_probe=FakeDatabaseProbe(healthy=True),
        model_status=ExplodingModelStatus(),
        sessions=offline_sessions(),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")

    assert response.json()["checks"]["model_registry"] == "missing"


# ---------------------------------------------------------------- the LLM mode (ADR 0073)


async def test_health_says_which_llm_answers_so_the_ui_can_show_demo_mode() -> None:
    app = create_app(
        database_probe=FakeDatabaseProbe(healthy=True),
        model_status=FakeModelStatus(loaded=True),
        sessions=offline_sessions(),
        llm=LLMStatus(mode="live", provider="openai", model="gpt-4.1-mini"),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/health")

    assert response.json()["llm"] == {"mode": "live", "provider": "openai", "model": "gpt-4.1-mini"}


def test_the_llm_status_of_replay_names_no_model() -> None:
    status = LLMStatus.of(Settings(llm_provider="replay", openai_model="gpt-4.1-mini"))

    assert status == LLMStatus(mode="replay", provider="replay", model=None)


@pytest.mark.parametrize(
    ("provider", "model"), [("openai", "gpt-4.1-mini"), ("anthropic", "claude-sonnet-5")]
)
def test_the_llm_status_of_a_live_provider_names_its_model(provider: str, model: str) -> None:
    settings = Settings(
        llm_provider=provider, openai_model="gpt-4.1-mini", anthropic_model="claude-sonnet-5"
    )

    assert LLMStatus.of(settings) == LLMStatus(mode="live", provider=provider, model=model)
