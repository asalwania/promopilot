"""The Planner agent (AG-03, SF-03, #47, ADR 0049): the LLM chooses which tools to call and
which optimiser options to set; the tools compute every number (ADR 0002).

The planner asks the LLM for one step at a time (`complete_with_tools`, ADR 0027), runs the
tools it asks for through the tool registry, where #45 traces every call, and sends each
result back. The plan is the latest successful `run_optimizer` result, whose plan revision is
built in process from the stored candidate set (`StoredRevisions`), never from tool JSON.

- A tool that raises is retried, then reaches the LLM as a structured `tool_failed` error; a
  `ToolError` (a call the tool cannot answer) reaches it at once, for the LLM to correct.
- The LLM may add or tighten the optimiser options of the planning request (regional budget
  caps, the KVI price tolerance, the promoted-SKU cap), never the brief's constraints: a call
  that loosens them is refused as `invalid_input` before it reaches the tool.
- If the LLM fails after its retries and fallback provider (a mid-round failure restarts the
  conversation once, ADR 0027), replay has no cassette, or no optimiser plan is reached within
  the step and tool-call limits, the deterministic default sequence plans instead (SF-03).

After the plan is chosen, the planner checks the scope's KVIs with `get_competitor_gaps` and
explains how the plan answers any undercut, from that tool's output (F-08 AC2).
"""

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from importlib.resources import files
from typing import Any, Final, Protocol
from uuid import UUID

import structlog
from pydantic import ValidationError

from promopilot.agents.planner import PlannedRevision
from promopilot.agents.state import DegradedReason
from promopilot.agents.tools import ToolError, ToolOk, ToolResult, ToolSpec
from promopilot.agents.tools.run_optimizer import RunOptimizerOutput
from promopilot.agents.trace import TracedToolRegistry, emit
from promopilot.competitors import CompetitorGaps
from promopilot.domain import DecisionMade, PlanningRequest
from promopilot.llm import CassetteMissError, LLMError, LLMProvider, Message
from promopilot.llm import ToolSpec as LLMToolSpec

log = structlog.get_logger(__name__)

MAX_STEPS: Final = 8
"""LLM steps per planning, a restart's included."""
MAX_TOOL_CALLS: Final = 16
"""Tool calls per planning; calls beyond it are not run."""
RETRY_DELAYS_S: Final = (0.5, 1.0)
"""Waits between the attempts of a tool that raises: three attempts in all."""

GENERATE_CANDIDATES: Final = "generate_candidates"
RUN_OPTIMIZER: Final = "run_optimizer"
GET_COMPETITOR_GAPS: Final = "get_competitor_gaps"
REQUEST_TOOLS: Final = frozenset({GENERATE_CANDIDATES, "compare_mechanisms"})
"""Tools the LLM passes a planning request to."""

FIXED_FIELDS: Final = (
    "as_of_week",
    "scope",
    "promo_window",
    "marketing_budget",
    "min_margin",
    "clearance_targets",
)
"""The brief's constraints, which the planner passes on unchanged."""

REMINDER: Final = (
    "No plan is selected yet. Call generate_candidates with the planning request, then "
    "run_optimizer with the candidate_set_id it returns."
)
DEGRADED_NOTES: Final = {
    DegradedReason.LLM_UNAVAILABLE: "The language model was unavailable",
    DegradedReason.CASSETTE_MISSING: "The language model was unavailable",
    DegradedReason.NO_OPTIMISED_PLAN: "The planner agent did not reach an optimised plan",
}

type Sleep = Callable[[float], Awaitable[None]]


class ToolCaller(Protocol):
    """The tools the planner offers the LLM (`ToolRegistry`, traced by #45)."""

    def specs(self) -> list[ToolSpec]: ...
    async def call(self, name: str, arguments: Mapping[str, Any]) -> ToolResult: ...


class RevisionSource(Protocol):
    """The plan revision of a solved candidate set (`StoredRevisions`)."""

    async def revision(self, candidate_set_id: UUID) -> PlannedRevision | None: ...


class DefaultSequence(Protocol):
    """The deterministic default sequence (`OptimisingPlanner`): generate, optimise, simulate."""

    async def plan(self, request: PlanningRequest) -> PlannedRevision: ...


@dataclass(frozen=True)
class AgentTools:
    """What the planner agent needs besides the LLM, and its limits."""

    tools: ToolCaller
    revisions: RevisionSource
    max_steps: int = MAX_STEPS
    max_tool_calls: int = MAX_TOOL_CALLS
    retry_delays_s: tuple[float, ...] = RETRY_DELAYS_S
    sleep: Sleep = asyncio.sleep


async def plan_with_tools(
    brief: str,
    request: PlanningRequest,
    llm: LLMProvider,
    agent: AgentTools,
    default: DefaultSequence,
) -> PlannedRevision:
    """Plan the request with the planner agent, or with the default sequence when the agent
    cannot (SF-03). The result carries the planner's notes and, when degraded, why.

    Raises only what building the plan revision or the default sequence raises
    (`PlanningError`); LLM and tool failures never propagate.
    """
    planner = _Planner(brief, request, llm, agent)
    outcome = await planner.converse()
    if isinstance(outcome, UUID):
        planned = await agent.revisions.revision(outcome)
        if planned is not None:
            return await planner.explained(planned, degraded=None)
        await _decide("planner_plan_gone", candidate_set_id=str(outcome))
        outcome = DegradedReason.NO_OPTIMISED_PLAN
    await _decide("planner_degraded", reason=outcome.value)
    return await planner.explained(await default.plan(request), degraded=outcome)


def loosening(given: PlanningRequest, proposed: PlanningRequest) -> tuple[str, ...]:
    """How `proposed` loosens the planning request the planner was `given`; empty when it only
    adds or tightens the optimiser options (ADR 0049)."""
    found = [
        f"changes {field}"
        for field in FIXED_FIELDS
        if getattr(proposed, field) != getattr(given, field)
    ]
    for region, cap in given.regional_budget_caps.items():
        proposed_cap = proposed.regional_budget_caps.get(region)
        if proposed_cap is None:
            found.append(f"drops the {region.value} regional budget cap")
        elif proposed_cap > cap:
            found.append(f"raises the {region.value} regional budget cap")
    if given.kvi_price_tolerance is not None:
        if proposed.kvi_price_tolerance is None:
            found.append("turns off the KVI price tolerance")
        elif proposed.kvi_price_tolerance > given.kvi_price_tolerance:
            found.append("widens the KVI price tolerance")
    sku_cap = given.max_promoted_skus_per_category_per_region
    if sku_cap is not None:
        proposed_skus = proposed.max_promoted_skus_per_category_per_region
        if proposed_skus is None:
            found.append("drops the promoted-SKU cap")
        elif proposed_skus > sku_cap:
            found.append("raises the promoted-SKU cap")
    return tuple(found)


class _Planner:
    def __init__(
        self, brief: str, request: PlanningRequest, llm: LLMProvider, agent: AgentTools
    ) -> None:
        self._request = request
        self._llm = llm
        self._agent = agent
        # Every call the planner makes is a trace event (ADR 0047).
        self._tools = TracedToolRegistry(agent.tools)
        self._specs = [
            LLMToolSpec(name=s.name, description=s.description, input_schema=s.input_schema)
            for s in agent.tools.specs()
        ]
        self._opening = (
            Message(role="system", content=planner_prompt()),
            Message(role="user", content=_opening_message(brief, request)),
        )
        self._calls: list[str] = []

    async def converse(self) -> UUID | DegradedReason:
        """The candidate set of the latest successful `run_optimizer`, or why there is none."""
        messages = list(self._opening)
        optimised: UUID | None = None
        restarted = reminded = False
        for _ in range(self._agent.max_steps):
            try:
                turn = await self._llm.complete_with_tools(self._specs, messages)
            except CassetteMissError as error:
                log.warning("planner_cassette_miss", error=str(error))
                return DegradedReason.CASSETTE_MISSING
            except LLMError as error:
                log.warning("planner_llm_failed", error=str(error), restarted=restarted)
                if restarted or len(messages) == len(self._opening):
                    return DegradedReason.LLM_UNAVAILABLE
                # A fallback provider may reject another provider's open tool round
                # (ADR 0027): start the conversation over, once.
                await _decide("planner_restarted", error=str(error))
                messages, optimised, restarted, reminded = list(self._opening), None, True, False
                continue
            messages.append(turn.as_message())
            if not turn.tool_calls:
                if optimised is not None:
                    return optimised
                if reminded:
                    return DegradedReason.NO_OPTIMISED_PLAN
                messages.append(Message(role="user", content=REMINDER))
                reminded = True
                continue
            for call in turn.tool_calls:
                if len(self._calls) >= self._agent.max_tool_calls:
                    await _decide("planner_tool_call_limit", limit=self._agent.max_tool_calls)
                    return optimised or DegradedReason.NO_OPTIMISED_PLAN
                result = await self._call(call.name, call.arguments)
                messages.append(
                    Message(role="tool", tool_call_id=call.id, content=result.model_dump_json())
                )
                if isinstance(result, ToolOk) and isinstance(result.output, RunOptimizerOutput):
                    optimised = result.output.candidate_set_id
        await _decide("planner_step_limit", limit=self._agent.max_steps)
        return optimised or DegradedReason.NO_OPTIMISED_PLAN

    async def explained(
        self, planned: PlannedRevision, *, degraded: DegradedReason | None
    ) -> PlannedRevision:
        """The plan with the planner's notes: why the default sequence planned it, and how it
        answers undercut KVIs."""
        notes: list[str] = []
        if degraded is not None:
            notes.append(
                f"{DEGRADED_NOTES[degraded]}, so the default sequence (generate candidates, "
                "optimise, simulate) planned this revision."
            )
        scope = self._request.scope
        arguments: dict[str, Any] = {
            "regions": [region.value for region in scope.regions],
            "categories": list(scope.categories),
            "kvi_only": True,
        }
        if scope.sku_ids:
            arguments["sku_ids"] = list(scope.sku_ids)
        gaps = await self._call(GET_COMPETITOR_GAPS, arguments)
        if isinstance(gaps, ToolOk) and isinstance(gaps.output, CompetitorGaps):
            notes.extend(
                gaps.output.undercut_response(
                    [planned_line.line for planned_line in planned.revision.lines]
                )
            )
        return PlannedRevision(
            planned.revision, planned.facts, notes=tuple(notes), degraded=degraded
        )

    async def _call(self, name: str, arguments: Mapping[str, Any]) -> ToolResult:
        """One tool call: refused if it loosens the brief, retried if the tool raises, and a
        structured `tool_failed` error once the retries are spent."""
        self._calls.append(name)
        refused = self._refusal(name, arguments)
        if refused is not None:
            await _decide("planner_call_refused", tool=name, reason=refused.message)
            return refused
        failure: Exception | None = None
        for delay in (*self._agent.retry_delays_s, None):
            try:
                return await self._tools.call(name, arguments)
            except Exception as error:
                log.warning("planner_tool_raised", tool=name, error=repr(error), exc_info=True)
                failure = error
            if delay is not None:
                await self._agent.sleep(delay)
        return ToolError(
            code="tool_failed",
            message=(
                f"{name} failed on every attempt: {type(failure).__name__}: {failure}. "
                "Try another analysis, or plan without this one."
            ),
        )

    def _refusal(self, name: str, arguments: Mapping[str, Any]) -> ToolError | None:
        if name not in REQUEST_TOOLS or not isinstance(arguments.get("request"), dict):
            return None
        try:
            proposed = PlanningRequest.model_validate(arguments["request"])
        except ValidationError:
            return None  # the tool reports what is wrong with it
        loosened = loosening(self._request, proposed)
        if not loosened:
            return None
        return ToolError(
            code="invalid_input",
            message=(
                f"the planning request may not loosen the brief: this call {'; '.join(loosened)}. "
                "Pass the planning request as given; only regional_budget_caps, "
                "kvi_price_tolerance and max_promoted_skus_per_category_per_region may be added "
                "or tightened."
            ),
        )


def planner_prompt() -> str:
    return (files("promopilot.agents") / "prompts" / "planner.md").read_text("utf-8")


def _opening_message(brief: str, request: PlanningRequest) -> str:
    # The brief travels as a JSON string: quoted data, never instructions (SPEC §9.6).
    return (
        "Planning request (JSON, read from the brief by the Context agent):\n"
        f"{request.model_dump_json()}\n\n"
        f"Brief (a JSON string written by the user):\n{json.dumps(brief, ensure_ascii=False)}"
    )


DECISIONS: Final = {
    "planner_plan_gone": "The optimiser's plan (candidate set {candidate_set_id}) is gone, so "
    "the default sequence plans instead.",
    "planner_degraded": "The planner agent could not plan ({reason}), so the deterministic "
    "default sequence plans instead.",
    "planner_restarted": "The LLM failed mid-round, so the planner restarts its conversation: "
    "{error}",
    "planner_tool_call_limit": "The planner reached its limit of {limit} tool calls.",
    "planner_step_limit": "The planner reached its limit of {limit} steps.",
    "planner_call_refused": "A {tool} call was refused: {reason}",
}
"""What each planner decision says in the session's trace."""


async def _decide(event: str, **fields: object) -> None:
    """A planner decision: logged, and a `decision` event in the session's trace (ADR 0047)."""
    log.info(event, **fields)
    await emit(DecisionMade(decision=event, summary=DECISIONS[event].format(**fields)))
