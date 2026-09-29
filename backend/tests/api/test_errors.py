"""One error schema for every API error (SPEC §6, #69, ADR 0071).

Every error answers `{detail, code, reference_id}`, and a 422 adds `errors`. The reference id is
the request's `X-Request-ID`, which every response carries. No error body shows a stack trace,
an exception's own text or the input it rejected.
"""

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from fastapi import APIRouter, FastAPI, HTTPException, status
from httpx import ASGITransport, AsyncClient

from promopilot.api.main import create_app
from promopilot.api.sessions import SessionService
from tests.offline import NoModel, offline_sessions

SECRET = "database password is hunter2"


class HealthyProbe:
    async def is_healthy(self) -> bool:
        return True


class ExplodingSessions(SessionService):
    """Reading any session fails with an unexpected error that must never reach the client."""

    async def get(self, session_id: UUID) -> Any:
        raise RuntimeError(SECRET)


def app_with(*, sessions: SessionService | None = None, max_body: int | None = None) -> FastAPI:
    extra: dict[str, Any] = {} if max_body is None else {"max_request_body_bytes": max_body}
    app = create_app(
        database_probe=HealthyProbe(),
        model_status=NoModel(),
        sessions=sessions or offline_sessions(),
        **extra,
    )
    # A router added later, like any other (#57's evals router), gets the schema too.
    extra_router = APIRouter(prefix="/api/test")

    @extra_router.post("/conflict", responses={status.HTTP_409_CONFLICT: {"description": "Busy"}})
    async def conflict() -> None:
        raise HTTPException(status.HTTP_409_CONFLICT, "A retrain is already running")

    app.include_router(extra_router)
    return app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app_with()), base_url="http://t") as c:
        yield c


def assert_error(response: Any, status_code: int, code: str) -> dict[str, Any]:
    assert response.status_code == status_code, response.text
    body: dict[str, Any] = response.json()
    assert body["code"] == code
    assert isinstance(body["detail"], str)
    assert body["detail"]
    assert body["reference_id"] == response.headers["x-request-id"]
    assert set(body) == {"detail", "code", "reference_id", "errors"}
    if status_code != 422:
        assert body["errors"] is None
    return body


async def test_every_response_carries_a_fresh_request_id(client: AsyncClient) -> None:
    first = await client.get("/health")
    second = await client.get("/health")

    assert first.status_code == 200
    ids = {first.headers["x-request-id"], second.headers["x-request-id"]}
    assert len(ids) == 2
    for request_id in ids:
        UUID(request_id)


async def test_an_unknown_route_is_not_found(client: AsyncClient) -> None:
    body = assert_error(await client.get("/api/nowhere"), 404, "not_found")

    assert body["detail"] == "Not Found"


async def test_a_conflict_keeps_its_sentence_as_the_detail(client: AsyncClient) -> None:
    body = assert_error(await client.post("/api/test/conflict"), 409, "conflict")

    assert body["detail"] == "A retrain is already running"


async def test_planning_unavailable_is_503_unavailable(client: AsyncClient) -> None:
    # ASGITransport runs no lifespan, so the agent graph's checkpoints are never opened.
    response = await client.post("/api/sessions", json={"brief": "Snacks push in the North"})

    body = assert_error(response, 503, "unavailable")
    assert "planning is unavailable" in body["detail"]


@pytest.mark.parametrize(
    ("path", "payload", "field"),
    [
        ("/api/sessions", {"brief": "x" * 2001}, "brief"),
        (f"/api/sessions/{UUID(int=1)}/amend", {"text": "x" * 2001}, "text"),
        (
            f"/api/sessions/{UUID(int=1)}/reject",
            {"revision_number": 1, "reason": "x" * 2001},
            "reason",
        ),
        (f"/api/sessions/{UUID(int=1)}/clarify", {"answers": {"q1": "x" * 2001}}, "answers"),
    ],
)
async def test_an_oversized_input_is_422_with_the_error_schema(
    client: AsyncClient, path: str, payload: dict[str, Any], field: str
) -> None:
    body = assert_error(await client.post(path, json=payload), 422, "validation_failed")

    assert body["detail"].startswith(field)
    assert "2000" in body["detail"]
    assert body["errors"][0]["loc"].startswith(f"body.{field}")
    # The rejected input is never echoed back.
    assert "x" * 100 not in str(body)


async def test_a_validators_message_reads_without_pydantics_prefix(client: AsyncClient) -> None:
    body = assert_error(
        await client.post("/api/sessions", json={"brief": "   "}), 422, "validation_failed"
    )

    assert body["detail"] == "brief: the brief is empty"
    assert body["errors"] == [{"loc": "body.brief", "message": "the brief is empty"}]


async def test_a_whole_body_rule_is_its_message_alone(client: AsyncClient) -> None:
    response = await client.post(f"/api/sessions/{UUID(int=1)}/amend", json={})

    body = assert_error(response, 422, "validation_failed")
    assert body["detail"] == "give either the amendment's text or accept_relaxation: true"


async def test_every_problem_is_listed(client: AsyncClient) -> None:
    response = await client.post(
        f"/api/sessions/{UUID(int=1)}/reject", json={"revision_number": 0, "extra": 1}
    )

    body = assert_error(response, 422, "validation_failed")
    assert {error["loc"] for error in body["errors"]} == {
        "body.revision_number",
        "body.reason",
        "body.extra",
    }


async def test_malformed_json_is_422(client: AsyncClient) -> None:
    response = await client.post(
        "/api/sessions", content=b"{not json", headers={"content-type": "application/json"}
    )

    assert_error(response, 422, "validation_failed")


async def test_a_bad_path_parameter_is_422(client: AsyncClient) -> None:
    body = assert_error(await client.get("/api/sessions/not-a-uuid"), 422, "validation_failed")

    assert body["errors"][0]["loc"] == "path.session_id"


@pytest.mark.parametrize(
    "answers",
    [
        {f"q{n}": "yes" for n in range(21)},
        {"q" * 65: "yes"},
    ],
    ids=["21 answers", "a 65-character question id"],
)
async def test_too_many_answers_or_too_long_an_id_is_422(
    client: AsyncClient, answers: dict[str, str]
) -> None:
    response = await client.post(f"/api/sessions/{UUID(int=1)}/clarify", json={"answers": answers})

    assert_error(response, 422, "validation_failed")
    # Even an oversized key is cut short where it names the problem.
    assert "q" * 65 not in response.text


async def test_an_unexpected_error_is_500_without_its_text_or_a_traceback() -> None:
    app = app_with(sessions=offline_sessions(ExplodingSessions))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        response = await c.get(f"/api/sessions/{UUID(int=1)}")

    body = assert_error(response, 500, "internal_error")
    assert SECRET not in response.text
    assert "Traceback" not in response.text
    assert "RuntimeError" not in response.text
    assert body["reference_id"] in body["detail"]


async def test_a_body_over_the_limit_is_413_before_it_is_read() -> None:
    app = app_with(max_body=1024)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        declared = await c.post("/api/sessions", json={"brief": "x" * 2000})

        async def chunks() -> AsyncIterator[bytes]:
            yield b'{"brief": "'
            for _ in range(20):
                yield b"x" * 100
            yield b'"}'

        streamed = await c.post(
            "/api/sessions", content=chunks(), headers={"content-type": "application/json"}
        )

    for response in (declared, streamed):
        body = assert_error(response, 413, "payload_too_large")
        assert "1024" in body["detail"]


async def test_a_body_within_the_limit_reaches_the_endpoint() -> None:
    app = app_with(max_body=1024)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:

        async def chunks() -> AsyncIterator[bytes]:
            yield b'{"brief": '
            yield b'"Snacks push"}'

        response = await c.post(
            "/api/sessions", content=chunks(), headers={"content-type": "application/json"}
        )

    # Past the guard: the offline app has no planning, so the endpoint answers 503.
    assert_error(response, 503, "unavailable")


def test_the_openapi_contract_documents_every_error_with_the_schema() -> None:
    schema = app_with().openapi()
    components = schema["components"]["schemas"]

    assert "HTTPValidationError" not in components
    assert set(components["ErrorResponse"]["properties"]) == {
        "detail",
        "code",
        "reference_id",
        "errors",
    }
    errors = 0
    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            for code, response in operation["responses"].items():
                if code.startswith(("4", "5")):
                    errors += 1
                    content = response["content"]["application/json"]["schema"]
                    assert content == {"$ref": "#/components/schemas/ErrorResponse"}, (
                        path,
                        method,
                        code,
                    )
            if "requestBody" in operation:
                assert "413" in operation["responses"], (path, method)
    assert errors > 20


def test_the_error_codes_are_a_published_enum() -> None:
    schema = app_with().openapi()

    codes = schema["components"]["schemas"]["ErrorResponse"]["properties"]["code"]
    assert set(codes["enum"]) >= {
        "not_found",
        "conflict",
        "payload_too_large",
        "validation_failed",
        "rate_limited",
        "unavailable",
        "timeout",
        "internal_error",
        "api_unreachable",
    }


@pytest.mark.parametrize(
    "path",
    [
        "/api/catalog/products?category=" + "c" * 65,
        "/api/inventory?category=" + "c" * 65,
        "/api/competitors/gaps?category=" + "c" * 65,
        "/api/relations/" + "S" * 65,
    ],
)
async def test_an_oversized_query_or_path_text_is_422(path: str) -> None:
    unused: Any = object()  # validation answers before any service is asked
    app = create_app(
        database_probe=HealthyProbe(),
        model_status=NoModel(),
        sessions=offline_sessions(),
        catalog=unused,
        competitors=unused,
        relations=unused,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        response = await c.get(path)

    body = assert_error(response, 422, "validation_failed")
    assert "64" in body["detail"]
