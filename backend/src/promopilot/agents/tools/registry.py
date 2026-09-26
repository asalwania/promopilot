"""The tool registry: typed, JSON-schema tools with pure handlers over injected dependencies.

Every number an agent uses comes through here (ADR 0002). A tool is a name, a description,
a pydantic input and output model (their JSON schemas are what the LLM sees) and an async
handler. Its dependencies are bound when the tool is built, never passed by the LLM.

`ToolRegistry.call` never raises for a bad call: an unknown tool, arguments that break the
input schema, or a `ToolCallError` from the handler all come back as a `ToolError` the planner
can hand to the LLM (ADR 0025). A bug in a handler still raises.
"""

from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, SerializeAsAny, ValidationError

ToolErrorCode = Literal["unknown_tool", "invalid_input", "model_unavailable"]


@dataclass(frozen=True)
class Tool[I: BaseModel, O: BaseModel]:
    name: str
    description: str
    input_type: type[I]
    output_type: type[O]
    handler: Callable[[I], Awaitable[O]]


class ToolSpec(BaseModel):
    """What the LLM is told about a tool."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]


class ToolOk(BaseModel):
    model_config = ConfigDict(frozen=True)

    ok: Literal[True] = True
    output: SerializeAsAny[BaseModel]


class ToolErrorDetail(BaseModel):
    model_config = ConfigDict(frozen=True)

    loc: str
    """Where in the arguments, e.g. `options.0.depth_pct`; empty for the whole call."""
    message: str


class ToolError(BaseModel):
    model_config = ConfigDict(frozen=True)

    ok: Literal[False] = False
    code: ToolErrorCode
    message: str
    details: tuple[ToolErrorDetail, ...] = ()


type ToolResult = ToolOk | ToolError


class ToolCallError(Exception):
    """Raised by a handler when a schema-valid call still cannot be answered."""

    def __init__(
        self, code: ToolErrorCode, message: str, details: Iterable[ToolErrorDetail] = ()
    ) -> None:
        super().__init__(message)
        self.error = ToolError(code=code, message=message, details=tuple(details))


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool[Any, Any]]) -> None:
        self._tools: dict[str, Tool[Any, Any]] = {}
        for tool in tools:
            if tool.name in self._tools:
                raise ValueError(f"two tools are named {tool.name}")
            self._tools[tool.name] = tool

    def specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name=tool.name,
                description=tool.description,
                input_schema=tool.input_type.model_json_schema(),
                output_schema=tool.output_type.model_json_schema(mode="serialization"),
            )
            for tool in self._tools.values()
        ]

    async def call(self, name: str, arguments: Mapping[str, Any]) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolError(
                code="unknown_tool",
                message=f"no tool named {name}; known tools: {', '.join(self._tools)}",
            )
        try:
            parsed = tool.input_type.model_validate(arguments)
        except ValidationError as error:
            return ToolError(
                code="invalid_input",
                message=f"the arguments do not match the {name} input schema",
                details=tuple(
                    ToolErrorDetail(loc=".".join(map(str, issue["loc"])), message=issue["msg"])
                    for issue in error.errors()
                ),
            )
        try:
            return ToolOk(output=await tool.handler(parsed))
        except ToolCallError as failure:
            return failure.error
