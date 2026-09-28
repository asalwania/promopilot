"""Agents: turn a brief into a promo plan a human approves (SPEC §9.6).

`build_graph` compiles the checkpointed agent graph (ADR 0046): the Context agent reads the
brief into a planning request with its assumptions, or asks at the Clarify interrupt
(ADR 0048), reading it by rules when the LLM is down (ADR 0053), the planner agent plans it
through the tools, falling back to the optimising planner (ADR 0038, ADR 0049), the Critic
validates the plan and reviews its risks, sending findings back to the planner at most 3 times
(ADR 0051), the Explainer writes grounded explanations with a template fallback (ADR 0050), and
the Approval interrupt waits for a decision.
"""

from promopilot.agents.amendments import relaxation_amendment
from promopilot.agents.assumptions import ContextReading
from promopilot.agents.checkpoints import Checkpoints, MemoryCheckpoints, PostgresCheckpoints
from promopilot.agents.context import BriefError, BriefReading, ClearanceAsk, RegionalCap
from promopilot.agents.critic import MAX_ATTEMPTS, CriticFeedback, FindingFeedback
from promopilot.agents.explainer import (
    ExplainerAnswer,
    LineRationale,
    explain_plan,
    explainer_prompt,
    plan_data,
    template_explanations,
)
from promopilot.agents.fallback import FALLBACK_CONFIDENCE, read_by_rules
from promopilot.agents.graph import (
    GraphSnapshot,
    GraphTools,
    Planner,
    PlanningGraph,
    SessionRecorder,
    build_graph,
    checkpoint_serializer,
    graph_state,
    resume_with_amendment,
    resume_with_answers,
    resume_with_decision,
    start_planning,
)
from promopilot.agents.planner import (
    OptimisingPlanner,
    PlannedRevision,
    PlannerData,
    PlanningError,
    StoredRevisions,
)
from promopilot.agents.planner_agent import (
    AgentTools,
    DefaultSequence,
    RevisionSource,
    ToolCaller,
    loosening,
    plan_with_tools,
)
from promopilot.agents.recording import (
    MANIFEST,
    CassetteManifest,
    RecordedPlanning,
    RecordedRevision,
    RecordedSession,
    RecordingError,
    ScriptStep,
    SessionScript,
    check_cassettes,
    load_scripts,
    manifest_problems,
    read_manifest,
    record_cassettes,
    ungrounded_answers,
)
from promopilot.agents.session import BriefData, read_context, read_planning_request
from promopilot.agents.state import (
    AmendAnswer,
    ApprovalAnswer,
    ApprovalRequest,
    ClarificationAnswer,
    ClarificationRequest,
    DegradedReason,
    PlanAttempt,
    PlanningState,
)
from promopilot.agents.trace import (
    LLMPricing,
    MemoryTrace,
    NoTrace,
    TracedProvider,
    TracedToolRegistry,
    TraceSink,
    emit,
    summarize,
    traced_node,
)

__all__ = [
    "FALLBACK_CONFIDENCE",
    "MANIFEST",
    "MAX_ATTEMPTS",
    "AgentTools",
    "AmendAnswer",
    "ApprovalAnswer",
    "ApprovalRequest",
    "BriefData",
    "BriefError",
    "BriefReading",
    "CassetteManifest",
    "Checkpoints",
    "ClarificationAnswer",
    "ClarificationRequest",
    "ClearanceAsk",
    "ContextReading",
    "CriticFeedback",
    "DefaultSequence",
    "DegradedReason",
    "ExplainerAnswer",
    "FindingFeedback",
    "GraphSnapshot",
    "GraphTools",
    "LLMPricing",
    "LineRationale",
    "MemoryCheckpoints",
    "MemoryTrace",
    "NoTrace",
    "OptimisingPlanner",
    "PlanAttempt",
    "PlannedRevision",
    "Planner",
    "PlannerData",
    "PlanningError",
    "PlanningGraph",
    "PlanningState",
    "PostgresCheckpoints",
    "RecordedPlanning",
    "RecordedRevision",
    "RecordedSession",
    "RecordingError",
    "RegionalCap",
    "RevisionSource",
    "ScriptStep",
    "SessionRecorder",
    "SessionScript",
    "StoredRevisions",
    "ToolCaller",
    "TraceSink",
    "TracedProvider",
    "TracedToolRegistry",
    "build_graph",
    "check_cassettes",
    "checkpoint_serializer",
    "emit",
    "explain_plan",
    "explainer_prompt",
    "graph_state",
    "load_scripts",
    "loosening",
    "manifest_problems",
    "plan_data",
    "plan_with_tools",
    "read_by_rules",
    "read_context",
    "read_manifest",
    "read_planning_request",
    "record_cassettes",
    "relaxation_amendment",
    "resume_with_amendment",
    "resume_with_answers",
    "resume_with_decision",
    "start_planning",
    "summarize",
    "template_explanations",
    "traced_node",
    "ungrounded_answers",
]
