from pathlib import Path
from typing import Any

import pytest

from promopilot.agents.tools import ToolSpec
from tools.tool_docs import main, render, tool_specs

REPO = Path(__file__).resolve().parents[3]

SPEC_TOOLS = [
    "estimate_demand",
    "get_scope_data",
    "get_inventory_status",
    "get_holidays",
    "get_competitor_gaps",
    "get_relations",
    "generate_candidates",
    "run_optimizer",
    "relax_constraints",
    "compare_mechanisms",
    "simulate_plan",
]

REGION = {"type": "string", "enum": ["North", "South"], "title": "Region"}


def spec(name: str, input_schema: dict[str, Any], output_schema: dict[str, Any]) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=f"What {name} does. It says more here.",
        input_schema=input_schema,
        output_schema=output_schema,
    )


def model(properties: dict[str, Any], required: list[str], **defs: Any) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": properties, "required": required}
    if defs:
        schema["$defs"] = defs
    return schema


def section(markdown: str, heading: str) -> str:
    start = markdown.index(heading + "\n")
    level = heading.split(" ", 1)[0]
    rest = markdown[start + len(heading) + 1 :]
    ends = [rest.find("\n" + h + " ") for h in ("#" * n for n in range(1, len(level) + 1))]
    ends = [end for end in ends if end >= 0]
    return rest[: min(ends)] if ends else rest


def test_each_tool_has_its_description_and_input_and_output_fields() -> None:
    markdown = render(
        [
            spec(
                "get_holidays",
                model(
                    {
                        "regions": {
                            "type": "array",
                            "items": {"$ref": "#/$defs/Region"},
                            "description": "Regions to list.",
                        },
                        "start_week": {"type": "integer", "minimum": 0},
                    },
                    ["start_week"],
                    Region=REGION,
                ),
                model({"holidays": {"type": "array", "items": {"type": "string"}}}, ["holidays"]),
            )
        ]
    )

    tool = section(markdown, "### `get_holidays`")
    assert "What get_holidays does. It says more here." in tool
    assert "| `regions` | array of [Region](#region) | no |  | Regions to list. |" in tool
    assert "| `start_week` | integer | yes | minimum 0 |  |" in tool
    assert "| `holidays` | array of string | yes |  |  |" in tool
    assert "one of `North`, `South`" in section(markdown, "### Region")


def test_the_index_links_every_tool_with_the_first_sentence_of_its_description() -> None:
    markdown = render([spec("run_optimizer", model({}, []), model({}, []))])

    assert "| [`run_optimizer`](#run_optimizer) | What run_optimizer does. |" in markdown


def test_a_schema_several_tools_share_is_listed_once() -> None:
    shared = model({"region": {"$ref": "#/$defs/Region"}}, ["region"], Region=REGION)

    markdown = render([spec("a_tool", shared, model({}, [])), spec("b_tool", shared, shared)])

    assert markdown.count("\n### Region\n") == 1


def test_two_different_schemas_with_one_name_are_refused() -> None:
    other = {"type": "string", "enum": ["East"], "title": "Region"}

    with pytest.raises(ValueError, match="Region"):
        render(
            [
                spec("a_tool", model({}, [], Region=REGION), model({}, [])),
                spec("b_tool", model({}, [], Region=other), model({}, [])),
            ]
        )


def test_the_page_lists_every_tool_error_code() -> None:
    markdown = render([])

    for code in ("unknown_tool", "invalid_input", "data_unavailable", "timeout"):
        assert f"`{code}`" in section(markdown, "## Errors")


def test_the_specs_are_every_spec_tool_in_the_order_the_planner_is_offered_them() -> None:
    assert [each.name for each in tool_specs()] == SPEC_TOOLS


def test_main_writes_the_page_with_lf_endings(tmp_path: Path) -> None:
    out = tmp_path / "tools.md"

    assert main([str(out)]) == 0

    written = out.read_bytes()
    assert b"\r\n" not in written
    assert written.decode("utf-8") == render(tool_specs())


def test_the_committed_tool_docs_match_the_tool_registry() -> None:
    committed = (REPO / "docs" / "tools.md").read_bytes().decode("utf-8")

    assert committed == render(tool_specs()), (
        "docs/tools.md is out of date with the tool registry: run `make tool-docs` and commit it"
    )
