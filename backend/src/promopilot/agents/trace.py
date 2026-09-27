"""Trace emission (SF-01, ADR 0047): every step of the agent graph becomes a trace event.

`build_graph` wraps every node with `traced_node`, which records the node's start and end and,
while the node runs, binds its session and name in a context variable. Code inside a node then
records anything else with one call, `await emit(payload)`:

- `TracedProvider` (wrapped around the graph's LLM) emits one token-usage event per billed call,
  priced with the configured prices when the call is made;
- `TracedToolRegistry.call` emits one tool-call event per call, with the arguments and an
  outline of the result;
- nodes emit their decisions, clarifications and findings themselves.

Events go to a `TraceSink`: `promopilot.data.TraceStore` in the API, `MemoryTrace` in tests, or
`NoTrace` by default. Outside a traced node, `emit` drops the event, as `record_usage` does.

While a node runs, its session id and name are also bound to structlog's context, so every log
line written inside it names them.
"""

import json
import time
from collections.abc import Awaitable, Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final, Protocol
from uuid import UUID

import structlog
from langgraph.errors import GraphInterrupt
from pydantic import BaseModel, JsonValue

from promopilot.agents.tools.registry import ToolOk, ToolResult, ToolSpec
from promopilot.config import ModelPrice
from promopilot.domain import (
    NodeFinished,
    NodeOutcome,
    NodeStarted,
    TokensUsed,
    ToolCalled,
    TraceEvent,
    TracePayload,
)
from promopilot.llm import LLMProvider, Message, ToolTurn, UsageMeter, track_usage
from promopilot.llm import ToolSpec as LLMToolSpec

SUMMARY_MAX_CHARS: Final = 2048
"""The longest a tool call's arguments or result summary may be, as JSON."""
SUMMARY_MAX_DEPTH: Final = 2
"""How many levels of nested objects a result summary keeps."""


class TraceSink(Protocol):
    """Where trace events go (`promopilot.data.TraceStore`): numbered 1, 2, ... per session,
    in the order they are appended."""

    async def append(self, session_id: UUID, node: str | None, payload: TracePayload) -> None: ...


class NoTrace:
    """Drops every event: the default when a graph is built without a trace sink."""

    async def append(self, session_id: UUID, node: str | None, payload: TracePayload) -> None:
        return None


class MemoryTrace:
    """Keeps every event in memory, numbered per session like `TraceStore` (for tests)."""

    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def append(self, session_id: UUID, node: str | None, payload: TracePayload) -> None:
        self.events.append(
            TraceEvent(
                id=len(self.of(session_id)) + 1,
                session_id=session_id,
                at=datetime.now(UTC),
                node=node,
                payload=payload,
            )
        )

    def of(self, session_id: UUID) -> list[TraceEvent]:
        """The session's events, in order."""
        return [event for event in self.events if event.session_id == session_id]


@dataclass(frozen=True)
class _Scope:
    sink: TraceSink
    session_id: UUID
    node: str


_scope: ContextVar[_Scope | None] = ContextVar("promopilot_trace", default=None)


async def emit(payload: TracePayload) -> None:
    """Record one trace event for the node running now; outside a traced node it is dropped."""
    scope = _scope.get()
    if scope is not None:
        await scope.sink.append(scope.session_id, scope.node, payload)


class SessionState(Protocol):
    """A graph state that names its planning session."""

    @property
    def session_id(self) -> UUID: ...


class Node[S](Protocol):
    """A graph node: it reads the state and returns its update."""

    def __call__(self, state: S) -> Awaitable[dict[str, object]]: ...


def traced_node[S: SessionState](sink: TraceSink, name: str, node: Node[S]) -> Node[S]:
    """`node`, recording its start and its end (completed, interrupted or failed) and letting
    the code it runs `emit` events for its session."""

    async def run(state: S) -> dict[str, object]:
        token = _scope.set(_Scope(sink=sink, session_id=state.session_id, node=name))
        logged = structlog.contextvars.bind_contextvars(session_id=str(state.session_id), node=name)
        try:
            await emit(NodeStarted())
            started = time.perf_counter_ns()
            try:
                update = await node(state)
            except GraphInterrupt:
                await emit(_finished(NodeOutcome.INTERRUPTED, started))
                raise
            except Exception as error:
                await emit(_finished(NodeOutcome.FAILED, started, error=str(error)))
                raise
            await emit(_finished(NodeOutcome.COMPLETED, started))
            return update
        finally:
            structlog.contextvars.reset_contextvars(**logged)
            _scope.reset(token)

    return run


def _finished(outcome: NodeOutcome, started_ns: int, error: str | None = None) -> NodeFinished:
    elapsed_ms = (time.perf_counter_ns() - started_ns) // 1_000_000
    return NodeFinished(outcome=outcome, duration_ms=elapsed_ms, error=error)


@dataclass(frozen=True)
class LLMPricing:
    """The configured model prices (`LLM_PRICES`) and rupee rate (`USD_INR_RATE`) that token
    usage is costed with (ADR 0027). With no prices, every model's cost is left out."""

    prices: Mapping[str, ModelPrice] = field(default_factory=dict)
    usd_inr_rate: float = 1.0


class TracedProvider:
    """An `LLMProvider` that emits a token-usage event for every billed call it makes,
    including a failed call that was billed and each provider tried on a fallback."""

    def __init__(self, inner: LLMProvider, pricing: LLMPricing) -> None:
        self._inner = inner
        self._pricing = pricing

    async def complete_structured[T: BaseModel](
        self, schema: type[T], messages: Sequence[Message]
    ) -> T:
        with track_usage() as meter:
            try:
                return await self._inner.complete_structured(schema, messages)
            finally:
                await self._report(meter)

    async def complete_with_tools(
        self, tools: Sequence[LLMToolSpec], messages: Sequence[Message]
    ) -> ToolTurn:
        with track_usage() as meter:
            try:
                return await self._inner.complete_with_tools(tools, messages)
            finally:
                await self._report(meter)

    async def _report(self, meter: UsageMeter) -> None:
        for usage in meter.usages:
            call = UsageMeter()
            call.record(usage)
            totals = call.totals(self._pricing.prices, usd_inr_rate=self._pricing.usd_inr_rate)
            priced = not totals.unpriced_models
            await emit(
                TokensUsed(
                    model=usage.model,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cost_usd=totals.cost_usd if priced else None,
                    cost_inr=totals.cost_inr if priced else None,
                )
            )


class Tools(Protocol):
    """A tool registry (`promopilot.agents.tools.ToolRegistry`)."""

    def specs(self) -> list[ToolSpec]: ...
    async def call(self, name: str, arguments: Mapping[str, Any]) -> ToolResult: ...


class TracedToolRegistry:
    """A tool registry whose every call emits a tool-call event: the arguments and an outline
    of the result, or the tool error's code and message. A call that raises is traced with
    error code `exception` and raises on."""

    def __init__(self, registry: Tools) -> None:
        self._registry = registry

    def specs(self) -> list[ToolSpec]:
        return self._registry.specs()

    async def call(self, name: str, arguments: Mapping[str, Any]) -> ToolResult:
        try:
            result = await self._registry.call(name, arguments)
        except Exception as error:
            await emit(
                ToolCalled(
                    tool=name,
                    arguments=_capped(_json(dict(arguments))),
                    ok=False,
                    error_code="exception",
                    result_summary=_capped(f"{type(error).__name__}: {error}"),
                )
            )
            raise
        if isinstance(result, ToolOk):
            called = ToolCalled(
                tool=name,
                arguments=_capped(_json(dict(arguments))),
                ok=True,
                result_summary=summarize(result.output.model_dump(mode="json")),
            )
        else:
            called = ToolCalled(
                tool=name,
                arguments=_capped(_json(dict(arguments))),
                ok=False,
                error_code=result.code,
                result_summary=summarize(
                    result.model_dump(mode="json", include={"message", "details"})
                ),
            )
        await emit(called)
        return result


def summarize(value: JsonValue) -> JsonValue:
    """An outline of a JSON value: scalars kept, lists counted, objects kept two levels deep,
    and the whole cut short to `SUMMARY_MAX_CHARS` of JSON."""
    return _capped(_outline(value, depth=0))


def _outline(value: JsonValue, depth: int) -> JsonValue:
    if isinstance(value, list):
        return f"<{len(value)} items>"
    if isinstance(value, dict):
        if depth >= SUMMARY_MAX_DEPTH:
            return f"<object with {len(value)} fields>"
        return {key: _outline(item, depth + 1) for key, item in value.items()}
    return value


def _capped(value: JsonValue) -> JsonValue:
    text = json.dumps(value, ensure_ascii=False)
    if len(text) <= SUMMARY_MAX_CHARS:
        return value
    return text[: SUMMARY_MAX_CHARS - 1] + "…"


def _json(value: object) -> JsonValue:
    """`value` as plain JSON; anything JSON cannot hold becomes its string."""
    decoded: JsonValue = json.loads(json.dumps(value, ensure_ascii=False, default=str))
    return decoded
