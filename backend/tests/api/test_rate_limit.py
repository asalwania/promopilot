"""Per-client rate limits on the endpoints that start or advance planning (SPEC §6, #70,
ADR 0079).

An in-process token bucket per client and group: creating, amending and clarifying a session
share the planning budget, and re-simulating a plan has its own. A request over the limit is
429 `rate_limited` with the error schema and a `Retry-After` header. The clock is injected, so
every test is deterministic.
"""

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from promopilot.api.main import build_app, create_app
from promopilot.api.rate_limit import RateLimiter, RateLimitGroup
from promopilot.api.schemas import PlanSimulationResponse
from promopilot.api.sessions import SessionService
from promopilot.config import Settings
from promopilot.domain import CompetitorReaction
from tests.api.test_errors import HealthyProbe, assert_error
from tests.offline import NoModel, offline_sessions

SESSION = UUID(int=7)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class StartingSessions(SessionService):
    """Starts a session without planning it: these tests are about the limiter."""

    async def start(self, brief: str) -> UUID:
        return uuid4()


class NoPlans:
    """Every session is unknown to the plans API (404)."""

    async def simulate(
        self, session_id: UUID, n_runs: int | None, competitor_reaction: CompetitorReaction | None
    ) -> PlanSimulationResponse | None:
        return None


def limited_app(limiter: RateLimiter | None) -> FastAPI:
    return create_app(
        database_probe=HealthyProbe(),
        model_status=NoModel(),
        sessions=offline_sessions(StartingSessions),
        plans=NoPlans(),  # type: ignore[arg-type]
        rate_limiter=limiter,
    )


def client_of(app: FastAPI, host: str = "203.0.113.7") -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app, client=(host, 5000)), base_url="http://t")


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
async def client(clock: FakeClock) -> AsyncIterator[AsyncClient]:
    limiter = RateLimiter(planning_per_minute=2, simulations_per_minute=3, clock=clock)
    async with client_of(limited_app(limiter)) as c:
        yield c


BRIEF = {"brief": "Snacks push in the North, ₹2 lakh"}


async def create(client: AsyncClient) -> Any:
    return await client.post("/api/sessions", json=BRIEF)


# The limiter over HTTP.


async def test_session_creation_over_the_limit_is_429_with_the_error_schema_and_retry_after(
    client: AsyncClient,
) -> None:
    assert (await create(client)).status_code == 202
    assert (await create(client)).status_code == 202

    response = await create(client)

    body = assert_error(response, 429, "rate_limited")
    assert body["detail"] == (
        "Too many planning requests from this client: at most 2 a minute. Try again in 30 s."
    )
    assert response.headers["retry-after"] == "30"


async def test_the_budget_refills_over_the_minute(client: AsyncClient, clock: FakeClock) -> None:
    for _ in range(2):
        await create(client)
    assert (await create(client)).status_code == 429

    clock.advance(29)
    assert (await create(client)).status_code == 429
    clock.advance(1)
    assert (await create(client)).status_code == 202
    assert (await create(client)).status_code == 429


async def test_creating_amending_and_clarifying_share_the_planning_budget(
    client: AsyncClient,
) -> None:
    await create(client)
    # No checkpoints are open offline, so the amendment itself is 503; it still counts.
    amended = await client.post(f"/api/sessions/{SESSION}/amend", json={"text": "cut budget"})
    assert amended.status_code == 503

    for response in (
        await create(client),
        await client.post(f"/api/sessions/{SESSION}/amend", json={"text": "cut budget"}),
        await client.post(f"/api/sessions/{SESSION}/clarify", json={"answers": {"q": "₹2 lakh"}}),
    ):
        assert_error(response, 429, "rate_limited")


async def test_every_attempt_counts_even_an_invalid_one_and_the_429_comes_first(
    client: AsyncClient,
) -> None:
    for _ in range(2):
        assert (await client.post("/api/sessions", json={"brief": ""})).status_code == 422

    assert_error(await client.post("/api/sessions", json={"brief": ""}), 429, "rate_limited")


async def test_simulations_have_their_own_budget(client: AsyncClient) -> None:
    for _ in range(2):
        await create(client)
    assert (await create(client)).status_code == 429

    for _ in range(3):
        simulated = await client.post(f"/api/plans/{SESSION}/simulate", json={})
        assert simulated.status_code == 404
    response = await client.post(f"/api/plans/{SESSION}/simulate", json={})

    body = assert_error(response, 429, "rate_limited")
    assert body["detail"] == (
        "Too many simulations from this client: at most 3 a minute. Try again in 20 s."
    )
    assert response.headers["retry-after"] == "20"


async def test_each_client_has_its_own_budget(clock: FakeClock) -> None:
    app = limited_app(RateLimiter(planning_per_minute=1, simulations_per_minute=1, clock=clock))
    async with client_of(app, "203.0.113.7") as first, client_of(app, "198.51.100.9") as second:
        assert (await create(first)).status_code == 202
        assert (await create(first)).status_code == 429

        assert (await create(second)).status_code == 202


async def test_reading_and_deciding_are_never_limited(client: AsyncClient) -> None:
    for _ in range(2):
        await create(client)

    for _ in range(5):
        assert (await client.get(f"/api/sessions/{SESSION}")).status_code != 429
        approved = await client.post(
            f"/api/sessions/{SESSION}/approve", json={"revision_number": 1}
        )
        assert approved.status_code != 429
        rejected = await client.post(
            f"/api/sessions/{SESSION}/reject", json={"revision_number": 1, "reason": "no"}
        )
        assert rejected.status_code != 429
        assert (await client.get("/api/health")).status_code == 200


async def test_a_limit_of_zero_turns_its_group_off(clock: FakeClock) -> None:
    app = limited_app(RateLimiter(planning_per_minute=0, simulations_per_minute=1, clock=clock))
    async with client_of(app) as client:
        for _ in range(50):
            assert (await create(client)).status_code == 202
        await client.post(f"/api/plans/{SESSION}/simulate", json={})
        assert (await client.post(f"/api/plans/{SESSION}/simulate", json={})).status_code == 429


async def test_without_a_limiter_nothing_is_limited() -> None:
    async with client_of(limited_app(None)) as client:
        for _ in range(50):
            assert (await create(client)).status_code == 202


def test_the_contract_documents_the_429_on_the_limited_operations() -> None:
    paths = limited_app(None).openapi()["paths"]
    limited = [
        ("/api/sessions", "post"),
        ("/api/sessions/{session_id}/amend", "post"),
        ("/api/sessions/{session_id}/clarify", "post"),
        ("/api/plans/{session_id}/simulate", "post"),
    ]
    for path, method in limited:
        response = paths[path][method]["responses"]["429"]
        assert response["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorResponse"
        }
        assert "Retry-After" in response["headers"]
    for path, method in [
        ("/api/sessions/{session_id}/approve", "post"),
        ("/api/sessions/{session_id}/reject", "post"),
        ("/api/sessions/{session_id}", "get"),
    ]:
        assert "429" not in paths[path][method]["responses"]


# The token bucket itself.


def test_a_bucket_allows_a_burst_of_its_limit_then_one_per_refill(clock: FakeClock) -> None:
    limiter = RateLimiter(planning_per_minute=3, simulations_per_minute=1, clock=clock)

    waits = [limiter.acquire("a", RateLimitGroup.PLANNING) for _ in range(4)]

    assert waits[:3] == [None, None, None]
    assert waits[3] == pytest.approx(20.0)
    clock.advance(10)
    assert limiter.acquire("a", RateLimitGroup.PLANNING) == pytest.approx(10.0)
    clock.advance(10)
    assert limiter.acquire("a", RateLimitGroup.PLANNING) is None


def test_a_refused_request_takes_no_token(clock: FakeClock) -> None:
    limiter = RateLimiter(planning_per_minute=1, simulations_per_minute=1, clock=clock)
    limiter.acquire("a", RateLimitGroup.PLANNING)

    for _ in range(10):
        assert limiter.acquire("a", RateLimitGroup.PLANNING) is not None
    clock.advance(60)

    assert limiter.acquire("a", RateLimitGroup.PLANNING) is None


def test_an_idle_bucket_never_holds_more_than_its_limit(clock: FakeClock) -> None:
    limiter = RateLimiter(planning_per_minute=2, simulations_per_minute=1, clock=clock)
    limiter.acquire("a", RateLimitGroup.PLANNING)
    clock.advance(3_600)

    waits = [limiter.acquire("a", RateLimitGroup.PLANNING) for _ in range(3)]

    assert waits[:2] == [None, None]
    assert waits[2] is not None


def test_buckets_that_have_refilled_are_forgotten(clock: FakeClock) -> None:
    limiter = RateLimiter(
        planning_per_minute=1, simulations_per_minute=1, clock=clock, max_clients=2
    )
    limiter.acquire("a", RateLimitGroup.PLANNING)
    limiter.acquire("b", RateLimitGroup.PLANNING)
    clock.advance(60)

    limiter.acquire("c", RateLimitGroup.PLANNING)

    assert limiter.tracked() == 1


def test_negative_limits_are_refused() -> None:
    with pytest.raises(ValueError, match="planning_per_minute"):
        RateLimiter(planning_per_minute=-1, simulations_per_minute=1)


def test_the_limits_come_from_the_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("RATE_LIMIT_PLANNING_PER_MINUTE", "RATE_LIMIT_SIMULATIONS_PER_MINUTE"):
        monkeypatch.delenv(name, raising=False)
    defaults = Settings()
    assert defaults.rate_limit_planning_per_minute == 20
    assert defaults.rate_limit_simulations_per_minute == 30

    monkeypatch.setenv("RATE_LIMIT_PLANNING_PER_MINUTE", "4")
    monkeypatch.setenv("RATE_LIMIT_SIMULATIONS_PER_MINUTE", "0")
    limiter = RateLimiter.from_settings(Settings())

    assert limiter.per_minute == {RateLimitGroup.PLANNING: 4, RateLimitGroup.SIMULATIONS: 0}
    monkeypatch.setenv("RATE_LIMIT_PLANNING_PER_MINUTE", "-1")
    with pytest.raises(ValueError, match="rate_limit_planning_per_minute"):
        Settings()


async def test_the_production_app_limits_planning_from_the_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://unused@127.0.0.1:1/unused")
    monkeypatch.setenv("RATE_LIMIT_PLANNING_PER_MINUTE", "1")
    monkeypatch.setenv("LOG_FORMAT", "console")

    app = build_app()

    async with client_of(app) as client:
        # ASGITransport runs no lifespan: no checkpoints are open, so planning is 503.
        assert (await create(client)).status_code == 503
        assert_error(await create(client), 429, "rate_limited")
