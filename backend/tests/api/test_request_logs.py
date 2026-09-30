"""Every line a request logs carries its request id, and a session's its session id (E11 #71,
ADR 0085).

The request guard binds the request id (ADR 0071's `X-Request-ID`) for the whole request and
logs one `http.request` line when it ends: method, route template, status and duration, never
the query string. A route with a `session_id` in its path binds it for the request.
"""

import io
import logging
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
import structlog
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient

from promopilot.api.main import create_app
from promopilot.api.rate_limit import RateLimiter
from promopilot.api.sessions import SessionService
from promopilot.domain import CompetitorReaction
from tests.api.test_errors import HealthyProbe
from tests.api.test_rate_limit import FakeClock, StartingSessions
from tests.logcapture import captured_logs
from tests.logcapture import json_lines as all_lines
from tests.offline import NoModel, offline_sessions

SESSION = UUID(int=11)
log = structlog.get_logger("promopilot.test")


class LoggingSessions(StartingSessions):
    """Reading a session logs a line (through structlog and the standard library) and finds
    nothing."""

    async def get(self, session_id: UUID) -> Any:
        log.info("sessions.read")
        logging.getLogger("promopilot.stdlib").warning("stdlib line")
        return None


class ExplodingSessions(SessionService):
    async def get(self, session_id: UUID) -> Any:
        raise RuntimeError("boom")


class LoggingPlans:
    async def simulate(
        self, session_id: UUID, n_runs: int | None, competitor_reaction: CompetitorReaction | None
    ) -> None:
        log.info("plans.simulating")
        return None


def app_with(sessions: SessionService | None = None, limiter: RateLimiter | None = None) -> FastAPI:
    app = create_app(
        database_probe=HealthyProbe(),
        model_status=NoModel(),
        sessions=sessions or offline_sessions(LoggingSessions),
        plans=LoggingPlans(),  # type: ignore[arg-type]
        rate_limiter=limiter,
    )
    extra = APIRouter(prefix="/api/test")

    @extra.get("/echo/{name}")
    async def echo(name: str) -> dict[str, str]:
        log.info("test.echo")
        return {"name": name}

    app.include_router(extra)
    return app


@pytest.fixture
def logged() -> Any:
    with captured_logs("json") as stream:
        yield stream


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app_with()), base_url="http://t") as c:
        yield c


def json_lines(stream: io.StringIO) -> list[dict[str, Any]]:
    """The app's lines: not the test client's own `httpx` line."""
    return [line for line in all_lines(stream) if line.get("logger") != "httpx"]


def access_line(stream: io.StringIO) -> dict[str, Any]:
    [line] = [line for line in json_lines(stream) if line["event"] == "http.request"]
    return line


async def test_every_line_of_a_request_carries_its_request_id(
    logged: io.StringIO, client: AsyncClient
) -> None:
    response = await client.get("/api/test/echo/x")

    request_id = response.headers["X-Request-ID"]
    lines = json_lines(logged)
    assert [line["event"] for line in lines] == ["test.echo", "http.request"]
    assert all(line["request_id"] == request_id for line in lines)


async def test_a_request_ends_with_one_access_line(
    logged: io.StringIO, client: AsyncClient
) -> None:
    await client.get("/api/test/echo/hunter2?password=hunter2&brief=secret-plan")

    line = access_line(logged)
    assert line["level"] == "info"
    assert (line["method"], line["route"], line["status"]) == ("GET", "/api/test/echo/{name}", 200)
    assert isinstance(line["duration_ms"], float)
    assert "hunter2" not in str(json_lines(logged))
    assert "secret-plan" not in str(json_lines(logged))


async def test_a_session_route_s_lines_carry_the_session_id(
    logged: io.StringIO, client: AsyncClient
) -> None:
    response = await client.get(f"/api/sessions/{SESSION}")

    assert response.status_code == 404
    lines = json_lines(logged)
    assert [line["event"] for line in lines] == ["sessions.read", "stdlib line", "http.request"]
    for line in lines:
        assert line["request_id"] == response.headers["X-Request-ID"]
        assert line["session_id"] == str(SESSION)
    assert access_line(logged)["route"] == "/api/sessions/{session_id}"


async def test_a_plan_route_s_lines_carry_the_session_id(
    logged: io.StringIO, client: AsyncClient
) -> None:
    await client.post(f"/api/plans/{SESSION}/simulate", json={})

    lines = json_lines(logged)
    assert [line["event"] for line in lines] == ["plans.simulating", "http.request"]
    assert all(line["session_id"] == str(SESSION) for line in lines)


async def test_a_path_that_is_not_a_session_id_binds_none(
    logged: io.StringIO, client: AsyncClient
) -> None:
    response = await client.get("/api/sessions/not-a-uuid-but-client-text")

    assert response.status_code == 422
    line = access_line(logged)
    assert line["status"] == 422
    assert "session_id" not in line
    assert "client-text" not in str(json_lines(logged))


async def test_nothing_stays_bound_after_the_request(
    logged: io.StringIO, client: AsyncClient
) -> None:
    await client.get(f"/api/sessions/{SESSION}")

    assert structlog.contextvars.get_contextvars() == {}


async def test_an_unexpected_error_s_lines_carry_the_request_id(logged: io.StringIO) -> None:
    app = app_with(sessions=offline_sessions(ExplodingSessions))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        response = await client.get(f"/api/sessions/{SESSION}")

    request_id = response.json()["reference_id"]
    [failure] = [line for line in json_lines(logged) if line["event"] == "api.unexpected_error"]
    assert failure["request_id"] == request_id
    assert failure["session_id"] == str(SESSION)
    assert "RuntimeError: boom" in failure["exception"]
    access = access_line(logged)
    assert (access["status"], access["request_id"]) == (500, request_id)


async def test_an_oversized_body_is_logged_as_413(logged: io.StringIO) -> None:
    app = app_with()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        await client.post("/api/sessions", content=b"x" * (300 * 1024))

    line = access_line(logged)
    assert (line["method"], line["status"]) == ("POST", 413)


async def test_a_rate_limited_request_is_logged_with_its_request_id(logged: io.StringIO) -> None:
    limiter = RateLimiter(planning_per_minute=1, simulations_per_minute=1, clock=FakeClock())
    app = app_with(limiter=limiter)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        await client.post("/api/sessions", json={"brief": "Clear the North's winter jackets"})
        refused = await client.post("/api/sessions", json={"brief": "and again"})

    assert refused.status_code == 429
    [*_, line] = [line for line in json_lines(logged) if line["event"] == "http.request"]
    assert (line["status"], line["request_id"]) == (429, refused.headers["X-Request-ID"])


@pytest.mark.parametrize("path", ["/health", "/api/health"])
async def test_health_checks_are_logged_only_at_debug(path: str) -> None:
    for level, expected in (("info", []), ("debug", ["http.request"])):
        with captured_logs(level=level) as stream:  # type: ignore[arg-type]
            async with AsyncClient(
                transport=ASGITransport(app=app_with()), base_url="http://t"
            ) as client:
                await client.get(path)
        assert [line["event"] for line in json_lines(stream)] == expected
