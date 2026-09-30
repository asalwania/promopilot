import json
from pathlib import Path
from typing import Any

import pytest

from tools.api_docs import main, render

REPO = Path(__file__).resolve().parents[3]

ERROR = {"$ref": "#/components/schemas/ErrorResponse"}


def json_body(schema: dict[str, Any]) -> dict[str, Any]:
    return {"application/json": {"schema": schema}}


def operation(tags: list[str] | None = None, **fields: Any) -> dict[str, Any]:
    op: dict[str, Any] = {
        "summary": "Do It",
        "responses": {"200": {"description": "Successful Response"}},
    }
    if tags is not None:
        op["tags"] = tags
    op.update(fields)
    return op


def document(
    paths: dict[str, Any] | None = None, schemas: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "openapi": "3.1.0",
        "info": {"title": "PromoPilot API", "version": "0.1.0"},
        "paths": paths or {},
        "components": {"schemas": schemas or {}},
    }


def section(markdown: str, heading: str) -> str:
    """The text under a heading, up to the next heading of the same or a higher level."""
    level = len(heading.split(" ", 1)[0])
    lines = markdown.split("\n")
    body = []
    for line in lines[lines.index(heading) + 1 :]:
        hashes = len(line) - len(line.lstrip("#"))
        if 0 < hashes <= level and line[hashes : hashes + 1] == " ":
            break
        body.append(line)
    return "\n".join(body)


def test_the_page_is_titled_from_the_contract_and_says_it_is_generated() -> None:
    markdown = render(document())

    assert markdown.startswith("# PromoPilot API\n")
    assert "Generated from [`docs/openapi.json`](openapi.json) by `make api-types`" in markdown
    assert "Do not edit it by hand" in markdown
    assert "Version 0.1.0, OpenAPI 3.1.0." in markdown


def test_endpoints_follow_the_spec_flow_untagged_ones_are_health_and_unknown_tags_come_last() -> (
    None
):
    markdown = render(
        document(
            {
                "/api/zeta": {"get": operation(["zeta"])},
                "/api/alpha": {"get": operation(["alpha"])},
                "/api/evals/latest": {"get": operation(["evals"])},
                "/api/sessions": {"post": operation(["sessions"])},
                "/health": {"get": operation()},
                "/api/plans/{session_id}/simulate": {"post": operation(["plans"])},
            }
        )
    )

    headings = [line for line in markdown.splitlines() if line.startswith("### ")]
    assert headings[:6] == [
        "### Health",
        "### Sessions",
        "### Plans",
        "### Evals",
        "### Alpha",
        "### Zeta",
    ]
    assert "#### `GET /health`" in section(markdown, "### Health")


def test_the_endpoint_index_links_every_operation_in_order() -> None:
    markdown = render(
        document(
            {
                "/api/sessions": {"post": operation(["sessions"], summary="Create Session")},
                "/api/sessions/{session_id}": {
                    "get": operation(["sessions"], summary="Get Session")
                },
            }
        )
    )

    assert (
        "| `POST` | [`/api/sessions`](#post-apisessions) | Create Session |\n"
        "| `GET` | [`/api/sessions/{session_id}`](#get-apisessionssession_id) | Get Session |"
    ) in markdown


def test_an_operation_shows_its_summary_description_parameters_body_and_responses() -> None:
    markdown = render(
        document(
            {
                "/api/sessions/{session_id}/amend": {
                    "post": operation(
                        ["sessions"],
                        summary="Amend Session",
                        description="Amend the request.\n\nThen re-plan.",
                        parameters=[
                            {
                                "in": "path",
                                "name": "session_id",
                                "required": True,
                                "schema": {"format": "uuid", "type": "string"},
                            },
                            {
                                "in": "query",
                                "name": "category",
                                "required": False,
                                "description": "Only this category",
                                "schema": {
                                    "anyOf": [{"maxLength": 64, "type": "string"}, {"type": "null"}]
                                },
                            },
                        ],
                        requestBody={
                            "content": json_body({"$ref": "#/components/schemas/AmendRequest"}),
                            "required": True,
                        },
                        responses={
                            "202": {
                                "description": "Successful Response",
                                "content": json_body({"$ref": "#/components/schemas/Created"}),
                            },
                            "429": {
                                "description": "Too many requests",
                                "content": json_body(ERROR),
                                "headers": {
                                    "Retry-After": {
                                        "description": "Whole seconds to wait.",
                                        "schema": {"type": "integer"},
                                    }
                                },
                            },
                        },
                    )
                }
            }
        )
    )

    body = section(markdown, "#### `POST /api/sessions/{session_id}/amend`")
    assert "**Amend Session**\n\nAmend the request.\n\nThen re-plan.\n" in body
    assert "| `session_id` | path | string (uuid) | yes |  |  |" in body
    assert (
        "| `category` | query | string or null | no | maxLength 64 | Only this category |" in body
    )
    assert "**Request body** (required): [AmendRequest](#amendrequest)" in body
    assert "| 202 | Successful Response | [Created](#created) |  |" in body
    assert (
        "| 429 | Too many requests | [ErrorResponse](#errorresponse) | "
        "`Retry-After` (integer): Whole seconds to wait. |"
    ) in body


def test_an_event_stream_response_names_the_schema_of_each_events_data() -> None:
    stream = {
        "text/event-stream": {
            "itemSchema": {
                "properties": {
                    "data": {
                        "contentMediaType": "application/json",
                        "contentSchema": {
                            "anyOf": [
                                {"$ref": "#/components/schemas/TraceEvent"},
                                {"$ref": "#/components/schemas/TraceStreamEnd"},
                            ]
                        },
                        "type": "string",
                    },
                    "event": {"type": "string"},
                },
                "required": ["data"],
                "type": "object",
            }
        }
    }
    markdown = render(
        document(
            {
                "/api/sessions/{session_id}/events": {
                    "get": operation(
                        ["sessions"],
                        responses={
                            "200": {"description": "Successful Response", "content": stream}
                        },
                    )
                }
            }
        )
    )

    assert (
        "| 200 | Successful Response | `text/event-stream`: each event's `data` is "
        "[TraceEvent](#traceevent) or [TraceStreamEnd](#tracestreamend) |  |"
    ) in markdown


def test_a_non_json_body_names_its_media_type() -> None:
    markdown = render(
        document(
            {
                "/export": {
                    "get": operation(
                        responses={
                            "200": {
                                "description": "A file",
                                "content": {"text/csv": {"schema": {"type": "string"}}},
                            }
                        }
                    )
                }
            }
        )
    )

    assert "| 200 | A file | `text/csv`: string |  |" in markdown


def test_a_schema_lists_its_fields_with_types_requiredness_constraints_and_descriptions() -> None:
    markdown = render(
        document(
            schemas={
                "PlanRevision": {
                    "description": "One plan revision.",
                    "properties": {
                        "number": {"minimum": 1, "type": "integer", "description": "From 1."},
                        "lines": {
                            "items": {"$ref": "#/components/schemas/PlanLine"},
                            "type": "array",
                        },
                        "diff": {
                            "anyOf": [
                                {"$ref": "#/components/schemas/RevisionDiff"},
                                {"type": "null"},
                            ],
                            "default": None,
                        },
                        "answers": {
                            "additionalProperties": {"maxLength": 2000, "type": "string"},
                            "maxProperties": 20,
                            "minProperties": 1,
                            "propertyNames": {"maxLength": 64},
                            "type": "object",
                        },
                        "status": {"enum": ["open", "final"], "type": "string"},
                        "kind": {"const": "decision", "type": "string"},
                        "share": {"exclusiveMinimum": 0, "maximum": 1, "type": "number"},
                        "tags": {"items": {"type": "string"}, "minItems": 1, "type": "array"},
                        "extra": {},
                        "cost": {"readOnly": True, "type": "number"},
                    },
                    "required": ["number", "lines"],
                    "type": "object",
                }
            }
        )
    )

    body = section(markdown, "### PlanRevision")
    assert body.startswith("\nOne plan revision.\n")
    assert "| Field | Type | Required | Constraints | Description |" in body
    assert "| `number` | integer | yes | minimum 1 | From 1. |" in body
    assert "| `lines` | array of [PlanLine](#planline) | yes |  |  |" in body
    assert "| `diff` | [RevisionDiff](#revisiondiff) or null | no | default `null` |  |" in body
    assert (
        "| `answers` | map of string to string | no | "
        "minProperties 1, maxProperties 20, keys maxLength 64, values maxLength 2000 |  |"
    ) in body
    assert "| `status` | string | no | one of `open`, `final` |  |" in body
    assert "| `kind` | string | no | always `decision` |  |" in body
    assert "| `share` | number | no | exclusiveMinimum 0, maximum 1 |  |" in body
    assert "| `tags` | array of string | no | minItems 1 |  |" in body
    assert "| `extra` | any | no |  |  |" in body
    assert "| `cost` | number | no | read-only |  |" in body


def test_schemas_are_listed_alphabetically_whatever_order_the_contract_has() -> None:
    markdown = render(document(schemas={"Zed": {"type": "object"}, "Alpha": {"type": "object"}}))

    assert markdown.index("### Alpha") < markdown.index("### Zed")


def test_enum_union_and_any_schemas_say_what_they_hold() -> None:
    markdown = render(
        document(
            schemas={
                "SessionStatus": {
                    "description": "Where a session is.",
                    "enum": ["planning", "final"],
                    "type": "string",
                },
                "TracePayload": {
                    "discriminator": {"propertyName": "kind"},
                    "oneOf": [
                        {"$ref": "#/components/schemas/NodeStarted"},
                        {"$ref": "#/components/schemas/TokensUsed"},
                    ],
                },
                "JsonValue": {},
            }
        )
    )

    assert "Where a session is.\n\nstring, one of `planning`, `final`.\n" in section(
        markdown, "### SessionStatus"
    )
    assert (
        "One of [NodeStarted](#nodestarted) or [TokensUsed](#tokensused), told apart by `kind`.\n"
    ) in section(markdown, "### TracePayload")
    assert "Any JSON value.\n" in section(markdown, "### JsonValue")


def test_table_cells_escape_pipes_and_fold_newlines() -> None:
    markdown = render(
        document(
            schemas={
                "Thing": {
                    "properties": {"a": {"type": "string", "description": "Either x | y.\nOr z."}},
                    "type": "object",
                }
            }
        )
    )

    assert "| `a` | string | no |  | Either x \\| y. Or z. |" in markdown


def test_the_errors_section_lists_the_error_codes_and_the_rate_limited_operations() -> None:
    markdown = render(
        document(
            {
                "/api/sessions": {
                    "post": operation(
                        ["sessions"],
                        responses={"429": {"description": "Too many", "content": json_body(ERROR)}},
                    )
                },
                "/api/models": {"get": operation(["models"])},
            },
            {
                "ErrorResponse": {
                    "properties": {
                        "code": {"enum": ["not_found", "rate_limited"], "type": "string"}
                    },
                    "type": "object",
                }
            },
        )
    )

    groups = [line for line in markdown.splitlines() if line.startswith("## ")]
    assert groups == ["## Errors", "## Endpoints", "## Schemas"]
    errors = section(markdown, "## Errors")
    assert "Every error response's body is [ErrorResponse](#errorresponse)" in errors
    assert "Its `code` is one of `not_found`, `rate_limited`." in errors
    assert "[`POST /api/sessions`](#post-apisessions)" in errors
    assert "/api/models" not in errors
    assert "../README.md#errors-limits-and-timeouts" in errors


def test_main_writes_lf_bytes_ending_in_one_newline(tmp_path: Path) -> None:
    source = tmp_path / "openapi.json"
    target = tmp_path / "api.md"
    source.write_text(
        json.dumps(document({"/health": {"get": operation(description="Liveness.\r\nOk.")}})),
        encoding="utf-8",
    )

    assert main([str(source), str(target)]) == 0

    written = target.read_bytes()
    assert b"\r" not in written
    assert written.endswith(b"\n")
    assert not written.endswith(b"\n\n")
    assert written.decode("utf-8") == render(json.loads(source.read_text(encoding="utf-8")))


def test_a_schema_whose_anchor_a_heading_already_has_is_refused() -> None:
    with pytest.raises(ValueError, match="Sessions"):
        render(
            document(
                {"/api/sessions": {"post": operation(["sessions"])}},
                {"Sessions": {"type": "object"}},
            )
        )


def test_rendering_is_the_same_whatever_order_the_paths_come_in() -> None:
    paths = {
        "/api/b": {"post": operation(["sessions"]), "get": operation(["sessions"])},
        "/api/a": {"get": operation(["sessions"])},
    }
    reordered = {path: dict(reversed(ops.items())) for path, ops in reversed(paths.items())}

    assert render(document(paths)) == render(document(reordered))


def test_the_committed_api_docs_match_the_committed_contract() -> None:
    contract = json.loads((REPO / "docs" / "openapi.json").read_text(encoding="utf-8"))
    committed = (REPO / "docs" / "api.md").read_bytes().decode("utf-8")

    assert committed == render(contract), (
        "docs/api.md is out of date with docs/openapi.json: run `make api-types` and commit it"
    )
