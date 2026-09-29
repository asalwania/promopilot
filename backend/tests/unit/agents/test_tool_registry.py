"""The tool registry: the single seam through which agents reach deterministic computation."""

import asyncio
from typing import Any

import pytest
from pydantic import BaseModel, Field

from promopilot.agents.tools import Tool, ToolCallError, ToolError, ToolOk, ToolRegistry


class AddInput(BaseModel):
    a: int
    b: int = Field(ge=0)


class AddOutput(BaseModel):
    total: int


async def add(arguments: AddInput) -> AddOutput:
    if arguments.a == 13:
        raise ToolCallError("model_unavailable", "thirteen is unlucky")
    return AddOutput(total=arguments.a + arguments.b)


ADD = Tool(
    name="add",
    description="Adds two numbers.",
    input_type=AddInput,
    output_type=AddOutput,
    handler=add,
)


def test_the_registry_lists_tools_with_their_schemas() -> None:
    [spec] = ToolRegistry([ADD]).specs()

    assert spec.name == "add"
    assert spec.description == "Adds two numbers."
    assert spec.input_schema == AddInput.model_json_schema()
    assert spec.output_schema == AddOutput.model_json_schema(mode="serialization")


async def test_valid_arguments_give_the_handler_output() -> None:
    result = await ToolRegistry([ADD]).call("add", {"a": 2, "b": 3})

    assert result == ToolOk(output=AddOutput(total=5))


async def test_an_unknown_tool_gives_a_typed_error() -> None:
    result = await ToolRegistry([ADD]).call("subtract", {"a": 2, "b": 3})

    assert isinstance(result, ToolError)
    assert result.code == "unknown_tool"
    assert "subtract" in result.message


@pytest.mark.parametrize(
    "arguments", [{"a": 2}, {"a": 2, "b": -1}, {"a": "two", "b": 1}, "not an object", None]
)
async def test_arguments_that_break_the_input_schema_give_a_typed_error(arguments: Any) -> None:
    result = await ToolRegistry([ADD]).call("add", arguments)

    assert isinstance(result, ToolError)
    assert result.code == "invalid_input"
    assert result.details
    assert all(detail.message for detail in result.details)


async def test_the_error_details_locate_the_bad_field() -> None:
    result = await ToolRegistry([ADD]).call("add", {"a": 2, "b": -1})

    assert isinstance(result, ToolError)
    assert [detail.loc for detail in result.details] == ["b"]


class Point(BaseModel):
    x: int


class PathInput(BaseModel):
    points: list[Point]
    label: dict[str, Point] = Field(default_factory=dict)


class Traced:
    """A handler that records every input it is given."""

    def __init__(self) -> None:
        self.inputs: list[PathInput] = []

    async def __call__(self, arguments: PathInput) -> AddOutput:
        self.inputs.append(arguments)
        return AddOutput(total=len(arguments.points))


@pytest.mark.parametrize(
    ("arguments", "loc"),
    [
        ({"points": [], "company_policy": {"margin_floor": 0}}, "company_policy"),
        ({"points": [{"x": 1, "ignore_rules": True}]}, "points.0.ignore_rules"),
        ({"points": [], "label": {"a": {"x": 1, "y": 2}}}, "label.a.y"),
    ],
)
async def test_a_key_the_input_schema_does_not_declare_is_refused_at_any_depth(
    arguments: dict[str, Any], loc: str
) -> None:
    # The input types ignore unknown keys, and their published schemas stay as they are
    # (the cassettes hash them); the registry itself refuses any key they do not declare, so
    # no argument is ever silently dropped (ADR 0079).
    handler = Traced()
    tool = Tool("path", "A path.", PathInput, AddOutput, handler)

    result = await ToolRegistry([tool]).call("path", arguments)

    assert isinstance(result, ToolError)
    assert result.code == "invalid_input"
    assert [detail.loc for detail in result.details] == [loc]
    assert handler.inputs == []
    assert ToolRegistry([tool]).specs()[0].input_schema == PathInput.model_json_schema()


async def test_a_failure_raised_by_the_handler_gives_a_typed_error() -> None:
    result = await ToolRegistry([ADD]).call("add", {"a": 13, "b": 0})

    assert result == ToolError(code="model_unavailable", message="thirteen is unlucky")


def test_tool_names_are_unique() -> None:
    with pytest.raises(ValueError, match="add"):
        ToolRegistry([ADD, ADD])


def test_results_serialise_to_json_for_the_llm() -> None:
    ok = ToolOk(output=AddOutput(total=5))
    error = ToolError(code="unknown_tool", message="no tool named x")

    assert ok.model_dump(mode="json") == {"ok": True, "output": {"total": 5}}
    assert error.model_dump(mode="json") == {
        "ok": False,
        "code": "unknown_tool",
        "message": "no tool named x",
        "details": [],
    }


class SlowInput(BaseModel):
    seconds: float


async def slow(arguments: SlowInput) -> AddOutput:
    await asyncio.sleep(arguments.seconds)
    return AddOutput(total=0)


SLOW = Tool(
    name="slow", description="Waits.", input_type=SlowInput, output_type=AddOutput, handler=slow
)


async def test_a_tool_that_takes_too_long_is_a_timeout_error() -> None:
    registry = ToolRegistry([SLOW], timeout_s=0.01)

    result = await registry.call("slow", {"seconds": 5})

    assert isinstance(result, ToolError)
    assert result.code == "timeout"
    assert result.message == "slow took longer than 0.01 s and was stopped"


async def test_a_tool_within_its_timeout_answers() -> None:
    registry = ToolRegistry([SLOW], timeout_s=5)

    assert await registry.call("slow", {"seconds": 0}) == ToolOk(output=AddOutput(total=0))
    assert ToolRegistry([SLOW]).timeout_s is None
