"""The agent graph (SPEC §9.6, ADR 0046): Context → Planner → Critic → Explainer → Approval
(interrupt) → Done, checkpointed so an interrupt survives an API restart.

In this slice the Context node reads the brief with the LLM (E3), the Planner runs the
deterministic default sequence (option generation → optimiser, with the relaxation when the
request is infeasible → simulation, ADR 0038/0044), the Critic runs `validate_plan` and keeps
what it finds as open issues, and the Explainer writes the template explanations. The Critic
loop (#48), the Clarify interrupt (#46) and amendments (#50) extend these edges.

Nodes record the session as they go through a `SessionRecorder` (`promopilot.data.
SessionStore`): the Planner saves the plan revision, the Critic its open issues, and Approval
records each decision once the interrupt is answered. The session moves to awaiting approval
only once `start_planning` returns with the thread paused at Approval, so the interrupt is
checkpointed before anyone can decide on it. Every step is checkpointed before the next runs
(durability "sync"). On resume LangGraph re-runs the Approval node from its start, so it does
nothing before the interrupt.
"""

import enum
import typing
from dataclasses import dataclass
from typing import Any, Final, Literal, Protocol
from uuid import UUID

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel

from promopilot.agents.explainer import template_explanations
from promopilot.agents.planner import PlannedRevision
from promopilot.agents.session import BriefData, read_planning_request
from promopilot.agents.state import (
    ApprovalAnswer,
    ApprovalRequest,
    PlanningState,
)
from promopilot.domain import (
    CompanyPolicy,
    DecisionKind,
    PlanDecision,
    PlanningRequest,
    PlanRevision,
    Violation,
)
from promopilot.guardrails import validate_plan
from promopilot.llm import LLMProvider

type PlanningGraph = CompiledStateGraph[PlanningState, None, PlanningState, PlanningState]

CONTEXT: Final = "context"
PLANNER: Final = "planner"
CRITIC: Final = "critic"
EXPLAINER: Final = "explainer"
APPROVAL: Final = "approval"
DONE: Final = "done"


class Planner(Protocol):
    """Plans a planning request (`promopilot.agents.OptimisingPlanner`)."""

    async def plan(self, request: PlanningRequest) -> PlannedRevision: ...


class SessionRecorder(Protocol):
    """What the graph records for its planning session (`promopilot.data.SessionStore`)."""

    async def save_revision(
        self, session_id: UUID, request: PlanningRequest, revision: PlanRevision
    ) -> None: ...

    async def save_open_issues(
        self, session_id: UUID, revision_number: int, issues: tuple[Violation, ...]
    ) -> None: ...

    async def record_decision(
        self,
        session_id: UUID,
        decision: DecisionKind,
        revision_number: int,
        reason: str | None,
    ) -> PlanDecision: ...


@dataclass(frozen=True)
class GraphTools:
    """The deterministic parts the graph's nodes call."""

    brief_data: BriefData
    planner: Planner
    sessions: SessionRecorder
    policy: CompanyPolicy


@dataclass(frozen=True)
class GraphSnapshot:
    """A thread's latest checkpoint: its state and the nodes it is paused before."""

    values: PlanningState
    paused_at: tuple[str, ...]

    @property
    def awaits_decision(self) -> bool:
        """Paused at the Approval interrupt, waiting for approve or reject."""
        return self.paused_at == (APPROVAL,)


def build_graph(
    tools: GraphTools, llm: LLMProvider, checkpointer: BaseCheckpointSaver[Any]
) -> PlanningGraph:
    """The compiled agent graph. Build `checkpointer` with `checkpoint_serializer()`."""

    async def context(state: PlanningState) -> dict[str, object]:
        return {"request": await read_planning_request(state.brief, llm, tools.brief_data)}

    async def planner(state: PlanningState) -> dict[str, object]:
        request = _required(state.request, "a planning request")
        planned = await tools.planner.plan(request)
        await tools.sessions.save_revision(state.session_id, request, planned.revision)
        return {
            "plan": planned.revision,
            "plan_facts": planned.facts,
            "iteration": state.iteration + 1,
        }

    async def critic(state: PlanningState) -> dict[str, object]:
        request = _required(state.request, "a planning request")
        plan = _required(state.plan, "a plan revision")
        findings = validate_plan(_required(state.plan_facts, "plan facts"), request, tools.policy)
        await tools.sessions.save_open_issues(state.session_id, plan.number, findings)
        return {"critic_findings": findings}

    async def explainer(state: PlanningState) -> dict[str, object]:
        plan = _required(state.plan, "a plan revision")
        return {"explanations": template_explanations(plan, state.critic_findings)}

    async def approval(state: PlanningState) -> dict[str, object]:
        plan = _required(state.plan, "a plan revision")
        answer = ApprovalAnswer.model_validate(
            interrupt(ApprovalRequest(revision_number=plan.number))
        )
        decision = await tools.sessions.record_decision(
            state.session_id, answer.decision, answer.revision_number, answer.reason
        )
        return {"approval": decision}

    def after_approval(state: PlanningState) -> Literal["done", "approval"]:
        decided = state.approval
        # A rejected revision waits at Approval again, open for an amendment (#50).
        return (
            DONE if decided is not None and decided.decision is DecisionKind.APPROVED else APPROVAL
        )

    async def done(state: PlanningState) -> dict[str, object]:
        return {}

    graph = StateGraph(PlanningState)
    graph.add_node(CONTEXT, context)
    graph.add_node(PLANNER, planner)
    graph.add_node(CRITIC, critic)
    graph.add_node(EXPLAINER, explainer)
    graph.add_node(APPROVAL, approval)
    graph.add_node(DONE, done)
    graph.add_edge(START, CONTEXT)
    graph.add_edge(CONTEXT, PLANNER)
    graph.add_edge(PLANNER, CRITIC)
    graph.add_edge(CRITIC, EXPLAINER)
    graph.add_edge(EXPLAINER, APPROVAL)
    graph.add_conditional_edges(APPROVAL, after_approval, [DONE, APPROVAL])
    graph.add_edge(DONE, END)
    return graph.compile(checkpointer=checkpointer)


def checkpoint_serializer() -> JsonPlusSerializer:
    """A checkpoint serializer that revives only the graph's own state types (ADR 0046).

    LangGraph revives any type named in a checkpoint unless it is given an allowlist; this one
    lists every pydantic model and enum reachable from the state and the Approval interrupt.
    """
    return JsonPlusSerializer(
        allowed_msgpack_modules=sorted(_types_of(PlanningState, ApprovalRequest, ApprovalAnswer))
    )


async def start_planning(
    graph: PlanningGraph, thread_id: str, session_id: UUID, brief: str
) -> list[str]:
    """Run a new session's graph until it pauses or ends; returns the nodes it ran, in order.

    Any node's error propagates (`BriefError`, `LLMError`, `PlanningError`, ...).
    """
    return await _run(graph, thread_id, PlanningState(session_id=session_id, brief=brief))


async def resume_with_decision(
    graph: PlanningGraph,
    thread_id: str,
    decision: DecisionKind,
    *,
    revision_number: int,
    reason: str | None,
) -> list[str]:
    """Answer the Approval interrupt of a paused thread; returns the nodes it ran, in order."""
    answer = ApprovalAnswer(decision=decision, revision_number=revision_number, reason=reason)
    return await _run(graph, thread_id, Command(resume=answer))


async def graph_state(graph: PlanningGraph, thread_id: str) -> GraphSnapshot | None:
    """The thread's latest checkpoint; None when the thread has none."""
    snapshot = await graph.aget_state(_config(thread_id))
    if not snapshot.values:
        return None
    return GraphSnapshot(
        values=PlanningState.model_validate(snapshot.values), paused_at=tuple(snapshot.next)
    )


async def _run(
    graph: PlanningGraph, thread_id: str, command: PlanningState | Command[Any]
) -> list[str]:
    """The nodes that ran, then the node the thread is paused at, if it is."""
    route = []
    async for update in graph.astream(
        command, _config(thread_id), stream_mode="updates", durability="sync"
    ):
        route += [node for node in update if not node.startswith("__")]
    snapshot = await graph.aget_state(_config(thread_id))
    return route + list(snapshot.next)


def _config(thread_id: str) -> Any:
    return {"configurable": {"thread_id": thread_id}}


def _required[T](value: T | None, what: str) -> T:
    if value is None:
        raise RuntimeError(f"the agent graph reached this node without {what}")
    return value


def _types_of(*roots: type[BaseModel]) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()

    def visit(annotation: object) -> None:
        for argument in typing.get_args(annotation):
            visit(argument)
        if not isinstance(annotation, type):
            return
        key = (annotation.__module__, annotation.__name__)
        if key in found:
            return
        if issubclass(annotation, BaseModel):
            found.add(key)
            for field in annotation.model_fields.values():
                visit(field.annotation)
        elif issubclass(annotation, enum.Enum):
            found.add(key)

    for root in roots:
        visit(root)
    return found
