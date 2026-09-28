"""The agent graph (SPEC §9.6, ADR 0046): Context → Planner → Critic → Explainer → Approval
(interrupt) → Done, checkpointed so an interrupt survives an API restart. Context goes to the
Clarify interrupt instead when it has questions, and each answer goes back to Context
(ADR 0048).

In this slice the Context node reads the brief with the LLM into a planning request with its
assumptions, or clarification questions (ADR 0048), the Planner is the LLM
planner agent over the tool registry when it is given one (#47, ADR 0049), falling back to
the deterministic default sequence (option generation → optimiser, with the relaxation when
the request is infeasible → simulation, ADR 0038/0044). The Critic checks each planner attempt
with `validate_plan` and the risk review, and sends its findings back to the planner agent
with feedback at most 3 times; then the best attempt goes on with its findings as open issues
(#48, ADR 0051). The Explainer has the LLM explain the plan, checked by numeric grounding, with
the template as its fallback (ADR 0050). Amendments (#50) extend these edges.

Nodes record the session as they go through a `SessionRecorder` (`promopilot.data.
SessionStore`): the Context node saves its assumptions, the Critic the chosen plan revision
with its open issues when it hands it on (planner attempts are drafts), the Explainer its
explanation, and Approval each decision once the interrupt is answered. The session moves to
awaiting approval (or clarification) only once `start_planning` returns with the thread paused
at the interrupt, so it is checkpointed before anyone can answer it. Every step is checkpointed
before the next runs (durability "sync"). On resume LangGraph re-runs an interrupted node from
its start, so Approval and Clarify do nothing before their interrupts.
"""

import enum
import typing
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Literal, Protocol
from uuid import UUID

import structlog
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel

from promopilot.agents.critic import (
    best_attempt,
    decide,
    handoff,
    review_attempt,
    route_summary,
)
from promopilot.agents.explainer import explain_plan
from promopilot.agents.planner import PlannedRevision
from promopilot.agents.planner_agent import AgentTools, plan_with_tools
from promopilot.agents.session import BriefData, read_context
from promopilot.agents.state import (
    ApprovalAnswer,
    ApprovalRequest,
    ClarificationAnswer,
    ClarificationRequest,
    PlanAttempt,
    PlanningState,
)
from promopilot.agents.trace import (
    LLMPricing,
    Node,
    NoTrace,
    TracedProvider,
    TraceSink,
    emit,
    traced_node,
)
from promopilot.domain import (
    Assumption,
    Clarification,
    ClarificationAsked,
    CompanyPolicy,
    DecisionKind,
    DecisionMade,
    OpenIssue,
    PlanDecision,
    PlanExplanation,
    PlanningRequest,
    PlanRevision,
)
from promopilot.guardrails import RiskThresholds
from promopilot.llm import LLMProvider

log = structlog.get_logger(__name__)

type PlanningGraph = CompiledStateGraph[PlanningState, None, PlanningState, PlanningState]

CONTEXT: Final = "context"
CLARIFY: Final = "clarify"
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

    async def save_assumptions(
        self, session_id: UUID, assumptions: tuple[Assumption, ...]
    ) -> None: ...

    async def save_revision(
        self, session_id: UUID, request: PlanningRequest, revision: PlanRevision
    ) -> None: ...

    async def save_open_issues(
        self, session_id: UUID, revision_number: int, issues: tuple[OpenIssue, ...]
    ) -> None: ...

    async def save_explanation(
        self, session_id: UUID, revision_number: int, explanation: PlanExplanation
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
    """The deterministic default sequence: the Planner itself without `agent`, the degraded
    path with it (ADR 0049)."""
    sessions: SessionRecorder
    policy: CompanyPolicy
    agent: AgentTools | None = None
    """The planner agent's tools; with them the LLM plans through the tool registry (#47)."""
    trace: TraceSink = field(default_factory=NoTrace)
    """Where the graph's trace events go (ADR 0047); dropped by default."""
    pricing: LLMPricing = field(default_factory=LLMPricing)
    """The prices token-usage events are costed with (ADR 0027)."""
    risk_thresholds: RiskThresholds = field(default_factory=RiskThresholds)
    """When the Critic's risk review flags a plan (`CRITIC_*` settings, ADR 0051)."""


@dataclass(frozen=True)
class GraphSnapshot:
    """A thread's latest checkpoint: its state and the nodes it is paused before."""

    values: PlanningState
    paused_at: tuple[str, ...]

    @property
    def awaits_decision(self) -> bool:
        """Paused at the Approval interrupt, waiting for approve or reject."""
        return self.paused_at == (APPROVAL,)

    @property
    def awaits_clarification(self) -> bool:
        """Paused at the Clarify interrupt, waiting for answers to its questions."""
        return self.paused_at == (CLARIFY,)


def build_graph(
    tools: GraphTools, llm: LLMProvider, checkpointer: BaseCheckpointSaver[Any]
) -> PlanningGraph:
    """The compiled agent graph. Build `checkpointer` with `checkpoint_serializer()`.

    Every node is traced (ADR 0047): add nodes with `add`, which wraps them in `traced_node`,
    so code inside them can `emit` events, and every LLM call made through `llm` is costed.
    """
    llm = TracedProvider(llm, tools.pricing)

    async def context(state: PlanningState) -> dict[str, object]:
        reading = await read_context(
            state.brief,
            llm,
            tools.brief_data,
            policy=tools.policy,
            clarifications=state.clarifications,
            amendments=state.amendments,
        )
        await tools.sessions.save_assumptions(state.session_id, reading.assumptions)
        if reading.questions:
            # Emitted here, not in Clarify: an interrupted node re-runs from its start on resume,
            # which would repeat the event.
            await emit(ClarificationAsked(questions=tuple(q.question for q in reading.questions)))
        return {
            "request": reading.request,
            "assumptions": reading.assumptions,
            "questions": reading.questions,
        }

    def after_context(state: PlanningState) -> Literal["clarify", "planner"]:
        return CLARIFY if state.questions else PLANNER

    async def clarify(state: PlanningState) -> dict[str, object]:
        answer = ClarificationAnswer.model_validate(
            interrupt(ClarificationRequest(questions=state.questions))
        )
        answered = tuple(
            Clarification(question=question, answer=answer.answers[question.id])
            for question in state.questions
        )
        return {"clarifications": (*state.clarifications, *answered), "questions": ()}

    async def planner(state: PlanningState) -> dict[str, object]:
        request = _required(state.request, "a planning request")
        if tools.agent is None:
            planned = await tools.planner.plan(request)
        else:
            # A loop-back from the Critic: its findings are the planner's feedback (ADR 0051).
            feedback = state.critic_findings if state.attempts else ()
            planned = await plan_with_tools(
                state.brief, request, llm, tools.agent, tools.planner, feedback=feedback
            )
        attempt = PlanAttempt(
            plan=planned.revision,
            facts=planned.facts,
            notes=planned.notes,
            degraded=planned.degraded,
        )
        return {"attempts": (*state.attempts, attempt), "iteration": state.iteration + 1}

    async def critic(state: PlanningState) -> dict[str, object]:
        request = _required(state.request, "a planning request")
        if not state.attempts:
            raise RuntimeError("the agent graph reached this node without a planner attempt")
        latest = state.attempts[-1]
        findings = await review_attempt(
            latest,
            request=request,
            policy=tools.policy,
            thresholds=tools.risk_thresholds,
            llm=llm,
        )
        attempts = (*state.attempts[:-1], latest.model_copy(update={"findings": findings}))
        route = handoff(attempts, agent_plans=tools.agent is not None)
        if route is None:
            await decide("loop_back", route_summary(None, attempts))
            return {"attempts": attempts, "critic_findings": findings}
        best = best_attempt(attempts)
        await decide(route.value, route_summary(route, attempts, chosen=best))
        await tools.sessions.save_revision(state.session_id, request, best.plan)
        await tools.sessions.save_open_issues(state.session_id, best.plan.number, best.findings)
        return {
            "attempts": attempts,
            "plan": best.plan,
            "plan_facts": best.facts,
            "critic_findings": best.findings,
            "planner_notes": best.notes,
            "planner_degraded": best.degraded,
        }

    def after_critic(state: PlanningState) -> Literal["planner", "explainer"]:
        loops = handoff(state.attempts, agent_plans=tools.agent is not None) is None
        return PLANNER if loops else EXPLAINER

    async def explainer(state: PlanningState) -> dict[str, object]:
        plan = _required(state.plan, "a plan revision")
        explanation = await explain_plan(
            llm,
            plan,
            request=_required(state.request, "a planning request"),
            policy=tools.policy,
            facts=state.plan_facts,
            open_issues=state.critic_findings,
            notes=state.planner_notes,
        )
        if explanation.fallback_reason is not None:
            log.warning(
                "explainer_fallback",
                session_id=str(state.session_id),
                revision_number=plan.number,
                reason=explanation.fallback_reason.value,
            )
            await emit(
                DecisionMade(
                    decision="explainer_fallback",
                    summary="The LLM's explanation was not used "
                    f"({explanation.fallback_reason.value}), so the template explains the plan.",
                )
            )
        await tools.sessions.save_explanation(state.session_id, plan.number, explanation)
        return {"explanations": explanation}

    async def approval(state: PlanningState) -> dict[str, object]:
        plan = _required(state.plan, "a plan revision")
        answer = ApprovalAnswer.model_validate(
            interrupt(ApprovalRequest(revision_number=plan.number))
        )
        decision = await tools.sessions.record_decision(
            state.session_id, answer.decision, answer.revision_number, answer.reason
        )
        await emit(
            DecisionMade(
                decision=decision.decision.value,
                summary=f"Plan revision {decision.revision_number} was approved."
                if decision.decision is DecisionKind.APPROVED
                else f"Plan revision {decision.revision_number} was rejected: {decision.reason}",
            )
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

    def add(name: str, node: Node[PlanningState]) -> None:
        graph.add_node(name, traced_node(tools.trace, name, node))

    add(CONTEXT, context)
    add(CLARIFY, clarify)
    add(PLANNER, planner)
    add(CRITIC, critic)
    add(EXPLAINER, explainer)
    add(APPROVAL, approval)
    add(DONE, done)
    graph.add_edge(START, CONTEXT)
    graph.add_conditional_edges(CONTEXT, after_context, [CLARIFY, PLANNER])
    graph.add_edge(CLARIFY, CONTEXT)
    graph.add_edge(PLANNER, CRITIC)
    graph.add_conditional_edges(CRITIC, after_critic, [PLANNER, EXPLAINER])
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
        allowed_msgpack_modules=sorted(
            _types_of(
                PlanningState,
                ApprovalRequest,
                ApprovalAnswer,
                ClarificationRequest,
                ClarificationAnswer,
            )
        )
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


async def resume_with_answers(
    graph: PlanningGraph, thread_id: str, answers: Mapping[str, str]
) -> list[str]:
    """Answer the Clarify interrupt of a paused thread, one answer per open question id;
    returns the nodes it ran, in order. The caller checks every question is answered."""
    answer = ClarificationAnswer(answers=dict(answers))
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
        if isinstance(annotation, typing.TypeAliasType):
            visit(annotation.__value__)
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
