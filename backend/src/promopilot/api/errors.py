"""One error schema for every API error (SPEC §6, E11 #69, ADR 0071).

Every error answers `ErrorResponse`: `{detail, code, reference_id}`, plus `errors` for a 422.

- `detail` is the message a promotions manager reads, as FastAPI's `detail` always was.
- `code` is chosen by the HTTP status.
- `reference_id` is the request's id, which every response also carries as `X-Request-ID`.

The routers keep raising `HTTPException`. `install_error_handling` turns it, request
validation, an oversized body and any unexpected exception into this schema, and makes the
OpenAPI contract say so. No body shows a stack trace, an exception's own text or the input it
rejected.
"""

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Final, Literal
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = structlog.get_logger(__name__)

REQUEST_ID_HEADER: Final = "X-Request-ID"
DEFAULT_MAX_REQUEST_BODY_BYTES: Final = 256 * 1024
"""20 answers of 2000 characters, each character escaped to 6 bytes of JSON, fit."""

ErrorCode = Literal[
    "bad_request",
    "not_found",
    "conflict",
    "payload_too_large",
    "validation_failed",
    "rate_limited",
    "internal_error",
    "api_unreachable",
    "unavailable",
    "timeout",
]
"""`api_unreachable` is the web proxy's 502 (ADR 0018); `rate_limited` is #70's 429."""

_CODES: Final[Mapping[int, ErrorCode]] = {
    404: "not_found",
    409: "conflict",
    413: "payload_too_large",
    422: "validation_failed",
    429: "rate_limited",
    500: "internal_error",
    502: "api_unreachable",
    503: "unavailable",
    504: "timeout",
}
_LOCATIONS: Final = frozenset({"body", "query", "path", "header", "cookie"})
_PREFIXES: Final = ("Value error, ", "Assertion failed, ")
_BODY_METHODS: Final = frozenset({"POST", "PUT", "PATCH"})


class FieldError(BaseModel):
    """One problem with the request: where it is, and what is wrong."""

    loc: str = Field(description="Where, e.g. `body.brief` or `path.session_id`.")
    message: str


class ErrorResponse(BaseModel):
    """What every API error answers (ADR 0071)."""

    detail: str = Field(description="What went wrong, in a sentence to show the user.")
    code: ErrorCode = Field(description="The kind of error, set by the HTTP status.")
    reference_id: str = Field(
        description="The request's id, also its `X-Request-ID` header: quote it to find the "
        "request in the logs."
    )
    errors: list[FieldError] | None = Field(
        default=None, description="Every problem with the request (422 only)."
    )


def error_code(status_code: int) -> ErrorCode:
    if status_code in _CODES:
        return _CODES[status_code]
    return "internal_error" if status_code >= 500 else "bad_request"


def install_error_handling(
    app: FastAPI, *, max_request_body_bytes: int = DEFAULT_MAX_REQUEST_BODY_BYTES
) -> None:
    """Answer every error of `app` with `ErrorResponse`, cap request bodies at
    `max_request_body_bytes` (413) and document both in its OpenAPI contract."""
    if max_request_body_bytes < 1:
        raise ValueError("max_request_body_bytes must be at least 1")
    app.add_exception_handler(StarletteHTTPException, _http_error)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_error)  # type: ignore[arg-type]
    app.add_middleware(RequestGuard, max_body_bytes=max_request_body_bytes)
    app.openapi = _documented(app, app.openapi)  # type: ignore[method-assign]


class RequestGuard:
    """Gives every HTTP request an id, refuses a body over the limit before the app reads it,
    and answers an unexpected exception with a 500 that names only the request id."""

    def __init__(self, app: ASGIApp, *, max_body_bytes: int) -> None:
        self._app = app
        self._max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        request_id = str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        started = False

        async def send_with_id(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                headers = list(message.get("headers", []))
                if not any(name.lower() == b"x-request-id" for name, _ in headers):
                    headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        if scope["method"] in _BODY_METHODS:
            body = await self._read_body(scope, receive)
            if body is None:
                too_large = _error_json(
                    request_id,
                    413,
                    f"The request body is larger than {self._max_body_bytes} bytes.",
                )
                await too_large(scope, receive, send_with_id)
                return
            receive = _replay(body, receive)
        try:
            await self._app(scope, receive, send_with_id)
        except Exception:
            if started:
                raise
            log.exception("api.unexpected_error", reference_id=request_id)
            failed = _error_json(
                request_id,
                500,
                f"Something went wrong on our side. Quote reference {request_id} to report it.",
            )
            await failed(scope, receive, send_with_id)

    async def _read_body(self, scope: Scope, receive: Receive) -> bytes | None:
        """The whole body, or None when it is (or says it is) over the limit."""
        for name, value in scope.get("headers", []):
            declared = name.lower() == b"content-length" and value.isdigit()
            if declared and int(value) > self._max_body_bytes:
                return None
        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                break
            chunk: bytes = message.get("body", b"")
            size += len(chunk)
            if size > self._max_body_bytes:
                return None
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        return b"".join(chunks)


def _replay(body: bytes, receive: Receive) -> Receive:
    """A `receive` that hands the app the body already read, then listens for a disconnect."""
    sent = False

    async def replayed() -> Message:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return await receive()

    return replayed


def _error_json(
    request_id: str,
    status_code: int,
    detail: str,
    *,
    errors: Sequence[FieldError] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body = ErrorResponse(
        detail=detail,
        code=error_code(status_code),
        reference_id=request_id,
        errors=None if errors is None else list(errors),
    )
    return JSONResponse(
        body.model_dump(mode="json", exclude_none=True),
        status_code=status_code,
        headers={**(headers or {}), REQUEST_ID_HEADER: request_id},
    )


def _request_id(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    return request_id if isinstance(request_id, str) else str(uuid4())


async def _http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
    return _error_json(
        _request_id(request), error.status_code, str(error.detail), headers=error.headers
    )


async def _validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
    problems = [_field_error(issue) for issue in error.errors()]
    detail = _readable(problems[0]) if problems else "The request is not valid."
    return _error_json(_request_id(request), 422, detail, errors=problems)


def _field_error(issue: Mapping[str, Any]) -> FieldError:
    message = str(issue.get("msg", "is not valid"))
    for prefix in _PREFIXES:
        message = message.removeprefix(prefix)
    return FieldError(loc=".".join(str(part) for part in issue.get("loc", ())), message=message)


def _readable(problem: FieldError) -> str:
    """`brief: the brief is empty`, or the message alone for a rule on the whole body."""
    parts = problem.loc.split(".") if problem.loc else []
    if parts and parts[0] in _LOCATIONS:
        parts = parts[1:]
    return f"{'.'.join(parts)}: {problem.message}" if parts else problem.message


_ERROR_REF: Final = {"$ref": "#/components/schemas/ErrorResponse"}
_TOO_LARGE: Final = "The request body is larger than MAX_REQUEST_BODY_BYTES"


def _documented(app: FastAPI, build: Callable[[], dict[str, Any]]) -> Callable[[], dict[str, Any]]:
    """`app.openapi`, with every 4xx and 5xx answered by `ErrorResponse`, a 413 on every
    operation that takes a body, and FastAPI's own validation-error schemas gone."""

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is not None:
            return app.openapi_schema
        schema = build()
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        definition = ErrorResponse.model_json_schema(
            ref_template="#/components/schemas/{model}", mode="serialization"
        )
        components.update(definition.pop("$defs", {}))
        components["ErrorResponse"] = definition
        for operations in schema.get("paths", {}).values():
            for operation in operations.values():
                responses = operation.setdefault("responses", {})
                if "requestBody" in operation:
                    responses.setdefault("413", {"description": _TOO_LARGE})
                for status_code, response in responses.items():
                    if status_code.startswith(("4", "5")):
                        response["content"] = {"application/json": {"schema": _ERROR_REF}}
        for unused in ("HTTPValidationError", "ValidationError"):
            components.pop(unused, None)
        app.openapi_schema = schema
        return schema

    return openapi
