"""Agents: turn a brief into a promo plan a human approves (SPEC §9.6).

`build_graph` compiles the checkpointed agent graph (ADR 0046): the Context agent reads the
brief, the planner agent plans it through the tools, falling back to the optimising planner
(ADR 0038, ADR 0049), the Critic validates the plan, the Explainer writes grounded
explanations with a template fallback (ADR 0050), and the Approval interrupt waits for a
decision.
"""

from promopilot.agents.checkpoints import Checkpoints, MemoryCheckpoints, PostgresCheckpoints
from promopilot.agents.context import BriefError, BriefReading
from promopilot.agents.explainer import (
    ExplainerAnswer,
    LineRationale,
    explain_plan,
    template_explanations,
)
from promopilot.agents.graph import (
    GraphSnapshot,
    GraphTools,
    Planner,
    PlanningGraph,
    SessionRecorder,
    build_graph,
    checkpoint_serializer,
    graph_state,
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
from promopilot.agents.recording import RecordedPlanning, RecordingError, record_cassettes
from promopilot.agents.session import BriefData, read_planning_request
from promopilot.agents.state import (
    ApprovalAnswer,
    ApprovalRequest,
    DegradedReason,
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
    "AgentTools",
    "ApprovalAnswer",
    "ApprovalRequest",
    "BriefData",
    "BriefError",
    "BriefReading",
    "Checkpoints",
    "DefaultSequence",
    "DegradedReason",
    "ExplainerAnswer",
    "GraphSnapshot",
    "GraphTools",
    "LLMPricing",
    "LineRationale",
    "MemoryCheckpoints",
    "MemoryTrace",
    "NoTrace",
    "OptimisingPlanner",
    "PlannedRevision",
    "Planner",
    "PlannerData",
    "PlanningError",
    "PlanningGraph",
    "PlanningState",
    "PostgresCheckpoints",
    "RecordedPlanning",
    "RecordingError",
    "RevisionSource",
    "SessionRecorder",
    "StoredRevisions",
    "ToolCaller",
    "TraceSink",
    "TracedProvider",
    "TracedToolRegistry",
    "build_graph",
    "checkpoint_serializer",
    "emit",
    "explain_plan",
    "graph_state",
    "loosening",
    "plan_with_tools",
    "read_planning_request",
    "record_cassettes",
    "resume_with_decision",
    "start_planning",
    "summarize",
    "template_explanations",
    "traced_node",
]
