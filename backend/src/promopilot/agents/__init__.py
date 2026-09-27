"""Agents: turn a brief into a promo plan a human approves (SPEC §9.6).

`build_graph` compiles the checkpointed agent graph (ADR 0046): the Context agent reads the
brief, the optimising planner plans it (ADR 0038), the Critic validates the plan, the
Explainer writes grounded explanations with a template fallback (ADR 0050), and the Approval
interrupt waits for a decision.
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
)
from promopilot.agents.recording import RecordingError, record_cassettes
from promopilot.agents.session import BriefData, read_planning_request
from promopilot.agents.state import (
    ApprovalAnswer,
    ApprovalRequest,
    PlanningState,
)

__all__ = [
    "ApprovalAnswer",
    "ApprovalRequest",
    "BriefData",
    "BriefError",
    "BriefReading",
    "Checkpoints",
    "ExplainerAnswer",
    "GraphSnapshot",
    "GraphTools",
    "LineRationale",
    "MemoryCheckpoints",
    "OptimisingPlanner",
    "PlannedRevision",
    "Planner",
    "PlannerData",
    "PlanningError",
    "PlanningGraph",
    "PlanningState",
    "PostgresCheckpoints",
    "RecordingError",
    "SessionRecorder",
    "build_graph",
    "checkpoint_serializer",
    "explain_plan",
    "graph_state",
    "read_planning_request",
    "record_cassettes",
    "resume_with_decision",
    "start_planning",
    "template_explanations",
]
