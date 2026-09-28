"""Trace events: what a planning session's agent graph did, step by step and in order (SF-01,
ADR 0047).

Every event belongs to one planning session and is numbered 1, 2, 3, ... within it; that
number is its SSE id, so a reconnecting client resumes after the last one it saw. Its payload
is one of a closed set of kinds, told apart by `kind`.
"""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class NodeOutcome(StrEnum):
    """How a node's run ended: it finished, paused at an interrupt, or raised."""

    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


class NodeStarted(BaseModel):
    """A graph node started running (again, when an interrupted node resumes)."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["node_started"] = "node_started"


class NodeFinished(BaseModel):
    """A graph node's run ended."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["node_finished"] = "node_finished"
    outcome: NodeOutcome
    duration_ms: int = Field(ge=0)
    error: str | None = None
    """Why the node failed; None unless `outcome` is failed."""


class ToolCalled(BaseModel):
    """A deterministic tool was called: its arguments and a summary of what it returned."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["tool_called"] = "tool_called"
    tool: str
    arguments: JsonValue
    """The arguments as called, or their JSON cut short when longer than the summary cap."""
    ok: bool
    error_code: str | None = None
    """The tool error's code when `ok` is false."""
    result_summary: JsonValue
    """The result's outline: scalars kept, lists counted, objects two levels deep."""


class DecisionMade(BaseModel):
    """A decision taken in the graph: a route a node chose, or a human's approve or reject."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["decision"] = "decision"
    decision: str
    """A short code, e.g. `plan_valid`, `open_issues`, `approved`, `rejected`."""
    summary: str
    """The decision in a sentence a promotions manager can read."""


class ClarificationAsked(BaseModel):
    """The Context agent paused to ask the manager these questions."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["clarification"] = "clarification"
    questions: tuple[str, ...]


class FindingRaised(BaseModel):
    """Something the Critic found in the plan."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["finding"] = "finding"
    source: str
    """What found it, e.g. `plan_validation` or `risk_review`."""
    code: str
    message: str


class TokensUsed(BaseModel):
    """One billed LLM call: its model, tokens and cost, priced when it was made."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["token_usage"] = "token_usage"
    model: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: float | None
    """None when the model has no configured price."""
    cost_inr: float | None


type TracePayload = Annotated[
    NodeStarted
    | NodeFinished
    | ToolCalled
    | DecisionMade
    | ClarificationAsked
    | FindingRaised
    | TokensUsed,
    Field(discriminator="kind"),
]


class TraceEvent(BaseModel):
    """One step of a planning session's trace."""

    model_config = ConfigDict(frozen=True)

    id: int = Field(ge=1)
    """Its position in the session's trace, from 1: the SSE event id."""
    session_id: UUID
    at: datetime
    node: str | None
    """The graph node it happened in."""
    payload: TracePayload


class SessionUsage(BaseModel):
    """What a planning session's LLM calls used and cost: the sums of its token-usage events."""

    model_config = ConfigDict(frozen=True)

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    cost_inr: float = 0.0
    unpriced_models: tuple[str, ...] = ()
    """Models with no configured price: their tokens count, their cost is left out."""
