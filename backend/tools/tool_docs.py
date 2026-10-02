"""Render the planner agent's tool contracts as Markdown, `docs/tools.md` (ADR 0088).

The contracts are the tool registry's own specs (ADR 0025): each tool's name, description and
the JSON schemas of its input and output, exactly what the LLM is shown. The registry is built
as the API builds it, through `planning_stack`, with inert dependencies: building a tool only
binds them, and no handler runs. Company policy and the planning settings take their defaults.

Deterministic, like `tools.api_docs` (ADR 0082): the page depends on the specs alone, and is
written as UTF-8 with LF endings. `make tool-docs` runs it, `make api-types` calls that, and a
test in `make test` fails when the committed page drifts.

    uv run python -m tools.tool_docs ../docs/tools.md
"""

import argparse
import re
import typing
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, cast

from promopilot.agents.stack import planning_stack
from promopilot.agents.tools import ToolErrorCode, ToolSpec
from promopilot.config import Settings
from promopilot.domain import CompanyPolicy
from promopilot.optimizer import SolverSettings
from promopilot.simulator import SimulationSettings
from tools.api_docs import check_anchors, constraints, render_schema, slug, table, type_of

Schema = dict[str, Any]

ERRORS = {
    "unknown_tool": "No tool has that name.",
    "invalid_input": "The arguments break the input schema, an undeclared key included, at any "
    "depth (ADR 0079). `details` lists each problem.",
    "model_unavailable": "No trained model the tool can use is registered.",
    "data_unavailable": "No data is loaded for the as-of week.",
    "tool_failed": "The tool kept raising after the planner's retries (ADR 0049).",
    "timeout": "The call ran longer than `TOOL_TIMEOUT_SECONDS` (ADR 0071).",
}
FIRST_SENTENCE = re.compile(r"^(.*?[.!?])(?:\s|$)", re.DOTALL)


def tool_specs() -> list[ToolSpec]:
    """Every tool the planner agent is offered, in the order it is offered them."""
    unused = cast(Any, None)
    stack = planning_stack(
        unused,
        unused,
        unused,
        policy=CompanyPolicy(),
        solver=SolverSettings(),
        simulation=SimulationSettings(
            n_runs=default("simulation_runs"), seed=default("simulation_seed")
        ),
        seed=default("optimizer_seed"),
        as_of_week=unused,
    )
    return stack.tools.specs()


def default(setting: str) -> int:
    """A setting's default, never the environment's value, so the page is the same anywhere."""
    return cast(int, Settings.model_fields[setting].default)


def first_sentence(text: str) -> str:
    found = FIRST_SENTENCE.match(text.strip())
    return found.group(1) if found else text.strip()


def fields(schema: Schema) -> list[str]:
    properties = schema.get("properties", {})
    if not properties:
        return ["No fields.", ""]
    required = set(schema.get("required", []))
    return [
        *table(
            ("Field", "Type", "Required", "Constraints", "Description"),
            (
                (
                    f"`{name}`",
                    type_of(field),
                    "yes" if name in required else "no",
                    ", ".join(constraints(field)),
                    field.get("description", ""),
                )
                for name, field in properties.items()
            ),
        ),
        "",
    ]


def shared_schemas(specs: Iterable[ToolSpec]) -> dict[str, Schema]:
    """Every named schema the tools use, once; one name must always mean one schema."""
    found: dict[str, Schema] = {}
    for each in specs:
        for schema in (each.input_schema, each.output_schema):
            for name, definition in schema.get("$defs", {}).items():
                if name in found and found[name] != definition:
                    raise ValueError(f"Two different schemas are both named {name}")
                found[name] = definition
    return found


def render_tool(spec: ToolSpec) -> list[str]:
    return [
        f"### `{spec.name}`",
        "",
        spec.description.strip(),
        "",
        "**Input**",
        "",
        *fields(spec.input_schema),
        "**Output**",
        "",
        *fields(spec.output_schema),
    ]


def render(specs: Sequence[ToolSpec]) -> str:
    """The Markdown tool reference for the registry's specs."""
    schemas = shared_schemas(specs)
    codes: tuple[str, ...] = typing.get_args(ToolErrorCode)
    lines = [
        "# PromoPilot tools",
        "",
        "The deterministic tools the planner agent is offered (SPEC §9.6), in the order it is "
        "offered them. Every number an agent uses comes from one of them (ADR 0002). Each "
        "tool's description and schemas below are exactly what the LLM is shown; its "
        "dependencies, company policy and as-of week are bound when the tool is built, never "
        "set by the LLM (ADR 0025, ADR 0032). How they fit together is in "
        "[the architecture document](architecture.md#tool-contracts).",
        "",
        "Generated from the tool registry by `make tool-docs` (`make api-types` runs it too). "
        "Do not edit it by hand: change the tool, run `make tool-docs` and commit the result. "
        "`make test` fails when this page drifts from the registry "
        "([ADR 0088](adr/0088-readme-for-judges-and-docs-checked-against-code.md)).",
        "",
        "## Errors",
        "",
        'A call never raises for a bad call: it returns `{"ok": true, "output": ...}` or '
        '`{"ok": false, "code", "message", "details"}`, which the planner hands back to the '
        "LLM. The codes:",
        "",
        *table(("Code", "Meaning"), ((f"`{code}`", ERRORS.get(code, "")) for code in codes)),
        "",
        "## Tools",
        "",
        *table(
            ("Tool", "Summary"),
            ((f"[`{s.name}`](#{slug(s.name)})", first_sentence(s.description)) for s in specs),
        ),
        "",
    ]
    for each in specs:
        lines += render_tool(each)
    lines += ["## Schemas", ""]
    for name in sorted(schemas):
        lines += render_schema(name, schemas[name])
    check_anchors(["Errors", "Tools", "Schemas", *(s.name for s in specs), *sorted(schemas)])
    return "\n".join(lines).rstrip("\n") + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("out", type=Path, help="the Markdown file to write (docs/tools.md)")
    args = parser.parse_args(argv)
    # Write bytes so Windows doesn't emit CRLF; the drift test compares bytes.
    args.out.write_bytes(render(tool_specs()).encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
