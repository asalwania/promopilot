"""Render the OpenAPI contract as the Markdown API reference, `docs/api.md` (ADR 0082).

Stdlib only, and deterministic: the output depends on the contract alone (no timestamps,
sorted where the contract's order does not matter) and is written as UTF-8 with LF endings,
so Windows and Linux produce the same bytes. `make api-types` runs it after exporting the
contract, and CI fails when the committed page differs.

    uv run python -m tools.api_docs ../docs/openapi.json ../docs/api.md
"""

import argparse
import json
import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

Schema = dict[str, Any]

# SPEC §10's flow; a tag not listed here follows, alphabetically.
TAG_ORDER = (
    "health",
    "sessions",
    "plans",
    "catalog",
    "competitors",
    "relations",
    "models",
    "evals",
)
# The only untagged operations are the health checks (`/health`, `/api/health`).
UNTAGGED = "health"
METHODS = ("get", "post", "put", "patch", "delete", "head", "options", "trace")
BOUNDS = (
    "minLength",
    "maxLength",
    "minimum",
    "exclusiveMinimum",
    "maximum",
    "exclusiveMaximum",
    "minItems",
    "maxItems",
    "minProperties",
    "maxProperties",
)
NULL = {"type": "null"}


def slug(heading: str) -> str:
    """GitHub's anchor for a heading: lower case, punctuation dropped, spaces to hyphens."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def link(name: str) -> str:
    return f"[{name}](#{slug(name)})"


def ref_name(ref: str) -> str:
    return ref.rsplit("/", 1)[-1]


def join_or(parts: Sequence[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " or " + parts[-1]


def number(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def literal(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return f"`{text}`"


def type_of(schema: Schema) -> str:
    """A schema's type in words, linking every named schema."""
    if "$ref" in schema:
        return link(ref_name(schema["$ref"]))
    for key in ("anyOf", "oneOf"):
        if key in schema:
            members = [type_of(member) for member in schema[key] if member != NULL]
            nullable = NULL in schema[key]
            return " or ".join(members) + (" or null" if nullable else "")
    kind = schema.get("type")
    if isinstance(kind, list):
        return " or ".join(type_of({**schema, "type": each}) for each in kind)
    if kind == "array":
        return "array of " + type_of(schema.get("items", {}))
    if kind == "object" and isinstance(schema.get("additionalProperties"), dict):
        return "map of string to " + type_of(schema["additionalProperties"])
    if kind:
        return f"{kind} ({schema['format']})" if "format" in schema else str(kind)
    return "any"


def constraints(schema: Schema) -> list[str]:
    """What a value must satisfy beyond its type, in the contract's own keywords."""
    found: list[str] = []
    for key in ("anyOf", "oneOf"):
        for member in schema.get(key, []):
            if "$ref" not in member and member != NULL:
                found += constraints(member)
    if "enum" in schema:
        found.append("one of " + ", ".join(literal(value) for value in schema["enum"]))
    if "const" in schema:
        found.append("always " + literal(schema["const"]))
    found += [f"{key} {number(schema[key])}" for key in BOUNDS if key in schema]
    if isinstance(schema.get("propertyNames"), dict):
        found += ["keys " + each for each in constraints(schema["propertyNames"])]
    if isinstance(schema.get("additionalProperties"), dict):
        found += ["values " + each for each in constraints(schema["additionalProperties"])]
    if isinstance(schema.get("items"), dict):
        found += ["items " + each for each in constraints(schema["items"])]
    if "default" in schema:
        found.append("default " + literal(schema["default"]))
    if schema.get("readOnly"):
        found.append("read-only")
    return found


def cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


def row(cells: Iterable[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def table(header: Sequence[str], rows: Iterable[Sequence[str]]) -> list[str]:
    return [row(header), row("---" for _ in header), *(row(cell(c) for c in r) for r in rows)]


def body_of(content: dict[str, Any]) -> str:
    """What a request or response body holds: a type for JSON, else its media type too."""
    parts = []
    for media, spec in sorted(content.items()):
        if "itemSchema" in spec:
            data = spec["itemSchema"].get("properties", {}).get("data", {})
            events = type_of(data.get("contentSchema", data))
            parts.append(f"`{media}`: each event's `data` is {events}")
        elif media == "application/json" and "schema" in spec:
            parts.append(type_of(spec["schema"]))
        elif "schema" in spec:
            parts.append(f"`{media}`: {type_of(spec['schema'])}")
        else:
            parts.append(f"`{media}`")
    return "; ".join(parts)


def headers_of(response: dict[str, Any]) -> str:
    return "; ".join(
        f"`{name}` ({type_of(header.get('schema', {}))}): {header.get('description', '')}".strip()
        for name, header in sorted(response.get("headers", {}).items())
    )


def tag_rank(tag: str) -> tuple[int, str]:
    return (TAG_ORDER.index(tag), "") if tag in TAG_ORDER else (len(TAG_ORDER), tag)


def operations(document: dict[str, Any]) -> list[tuple[str, str, str, dict[str, Any]]]:
    """Every (tag, method, path, operation), in page order."""
    found = [
        (op.get("tags", [UNTAGGED])[0], method, path, op)
        for path, item in document.get("paths", {}).items()
        for method, op in item.items()
        if method in METHODS
    ]
    return sorted(found, key=lambda o: (tag_rank(o[0]), o[2], METHODS.index(o[1])))


def heading_of(method: str, path: str) -> str:
    return f"`{method.upper()} {path}`"


def title(tag: str) -> str:
    return tag[:1].upper() + tag[1:]


def render_operation(method: str, path: str, op: dict[str, Any]) -> list[str]:
    lines = [f"#### {heading_of(method, path)}", ""]
    if op.get("summary"):
        lines += [f"**{op['summary']}**", ""]
    if op.get("description"):
        lines += [op["description"].strip(), ""]
    if op.get("parameters"):
        lines += ["**Parameters**", ""]
        lines += table(
            ("Name", "In", "Type", "Required", "Constraints", "Description"),
            (
                (
                    f"`{p['name']}`",
                    p["in"],
                    type_of(p.get("schema", {})),
                    "yes" if p.get("required") else "no",
                    ", ".join(constraints(p.get("schema", {}))),
                    p.get("description", p.get("schema", {}).get("description", "")),
                )
                for p in op["parameters"]
            ),
        )
        lines.append("")
    if "requestBody" in op:
        body = op["requestBody"]
        required = " (required)" if body.get("required") else ""
        lines += [f"**Request body**{required}: {body_of(body.get('content', {}))}", ""]
    lines += ["**Responses**", ""]
    lines += table(
        ("Status", "Description", "Body", "Headers"),
        (
            (
                status,
                response.get("description", ""),
                body_of(response.get("content", {})),
                headers_of(response),
            )
            for status, response in sorted(op.get("responses", {}).items())
        ),
    )
    return [*lines, ""]


def render_schema(name: str, schema: Schema) -> list[str]:
    lines = [f"### {name}", ""]
    if schema.get("description"):
        lines += [schema["description"].strip(), ""]
    properties = schema.get("properties", {})
    if properties:
        required = set(schema.get("required", []))
        lines += table(
            ("Field", "Type", "Required", "Constraints", "Description"),
            (
                (
                    f"`{field}`",
                    type_of(spec),
                    "yes" if field in required else "no",
                    ", ".join(constraints(spec)),
                    spec.get("description", ""),
                )
                for field, spec in properties.items()
            ),
        )
    elif "oneOf" in schema or "anyOf" in schema:
        union: list[Schema] = schema["oneOf"] if "oneOf" in schema else schema["anyOf"]
        members = [type_of(member) for member in union]
        told_apart = schema.get("discriminator", {}).get("propertyName")
        suffix = f", told apart by `{told_apart}`" if told_apart else ""
        lines.append(f"One of {join_or(members)}{suffix}.")
    elif not schema or set(schema) <= {"description", "title"}:
        lines.append("Any JSON value.")
    else:
        lines.append(", ".join([type_of(schema), *constraints(schema)]) + ".")
    return [*lines, ""]


def render_errors(document: dict[str, Any], ops: list[tuple[str, str, str, Any]]) -> list[str]:
    schemas = document.get("components", {}).get("schemas", {})
    if "ErrorResponse" not in schemas:
        return []
    lines = [
        "## Errors",
        "",
        f"Every error response's body is {link('ErrorResponse')}: a sentence to show "
        "(`detail`), a `code`, the request's `reference_id` and, for a 422, every problem "
        "(`errors`).",
    ]
    codes = schemas["ErrorResponse"].get("properties", {}).get("code", {}).get("enum")
    if codes:
        lines[-1] += " Its `code` is one of " + ", ".join(f"`{c}`" for c in codes) + "."
    lines += [
        "",
        "The guide's [Errors, limits and timeouts](guide/api-usage.md#errors-limits-and-timeouts) "
        "explains each code, the input limits, the timeouts and the rate limits "
        "([ADR 0071](adr/0071-one-error-schema-input-limits-and-timeouts.md), "
        "[ADR 0079](adr/0079-briefs-are-data-and-per-client-rate-limits.md)).",
        "",
    ]
    limited = [(m, p) for _, m, p, op in ops if "429" in op.get("responses", {})]
    if limited:
        lines += [
            "These operations are rate-limited per client and answer `429` with a "
            "`Retry-After` header when a client is over its limit:",
            "",
            *(f"- [{heading_of(m, p)}](#{slug(heading_of(m, p))})" for m, p in limited),
            "",
        ]
    return lines


def check_anchors(headings: Iterable[str]) -> None:
    seen: dict[str, str] = {}
    for heading in headings:
        anchor = slug(heading)
        if anchor in seen:
            raise ValueError(
                f"The headings {seen[anchor]!r} and {heading!r} would share the anchor #{anchor}"
            )
        seen[anchor] = heading


def render(document: dict[str, Any]) -> str:
    """The Markdown API reference for an OpenAPI document."""
    info = document.get("info", {})
    ops = operations(document)
    schemas = document.get("components", {}).get("schemas", {})
    lines = [
        f"# {info.get('title', 'API')}",
        "",
        "Generated from [`docs/openapi.json`](openapi.json) by `make api-types` "
        "(`make api-docs` alone rewrites this page from the committed contract). "
        "Do not edit it by hand: change the API, run `make api-types` and commit the result. "
        "CI fails when this page drifts from the contract "
        "([ADR 0082](adr/0082-api-docs-generated-from-the-contract.md)).",
        "",
        f"Version {info.get('version', '?')}, OpenAPI {document.get('openapi', '?')}. "
        "With the API running, its interactive docs are at http://localhost:8000/docs.",
        "",
        *render_errors(document, ops),
        "## Endpoints",
        "",
        *table(
            ("Method", "Path", "Summary"),
            (
                (f"`{m.upper()}`", f"[`{p}`](#{slug(heading_of(m, p))})", op.get("summary", ""))
                for _, m, p, op in ops
            ),
        ),
        "",
    ]
    tags: list[str] = []
    for tag, method, path, op in ops:
        if tag not in tags:
            tags.append(tag)
            lines += [f"### {title(tag)}", ""]
        lines += render_operation(method, path, op)
    lines += ["## Schemas", ""]
    for name in sorted(schemas):
        lines += render_schema(name, schemas[name])
    check_anchors(
        [
            "Errors",
            "Endpoints",
            "Schemas",
            *(title(t) for t in tags),
            *(heading_of(m, p) for _, m, p, _ in ops),
            *sorted(schemas),
        ]
    )
    text = "\n".join(lines).replace("\r\n", "\n").replace("\r", "\n")
    return text.rstrip("\n") + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("openapi", type=Path, help="the OpenAPI document (docs/openapi.json)")
    parser.add_argument("out", type=Path, help="the Markdown file to write (docs/api.md)")
    args = parser.parse_args(argv)
    document = json.loads(args.openapi.read_text(encoding="utf-8"))
    # Write bytes so Windows doesn't emit CRLF; CI diffs this file on Linux.
    args.out.write_bytes(render(document).encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
