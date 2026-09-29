"""Evaluation (SPEC §12, ADR 0056): the oracle, the scenarios, the world they are planned in,
the runner, the metrics and the report.

`run(scenarios, provider, runs_per_scenario, world=..., settings=...)` plays each scenario
through the full agent graph and scores its final plan revision; `write_report` writes the
report. The only package besides promopilot.datagen allowed to read the ground truth.
"""

from promopilot.evals.oracle import LineOutcome, Oracle, PlanOutcome
from promopilot.evals.report import (
    REPORT_DIR,
    EvalReport,
    Metric,
    ReportPaths,
    RunOutcome,
    RunResult,
    ScenarioResult,
    render_markdown,
    write_report,
)
from promopilot.evals.runner import run
from promopilot.evals.scenarios import (
    SCENARIO_DIR,
    AcceptRelaxation,
    Amendment,
    AsksClarification,
    DeclaresInfeasible,
    DiffChanges,
    ExcludesRegion,
    ExpectedProperty,
    FlagsAssumption,
    KviResponsePresent,
    MeetsClearance,
    NoStrongSubstitutesTogether,
    RelaxationTouches,
    RequestLabels,
    Scenario,
    ScenarioGroup,
    load_scenario,
    load_scenarios,
)
from promopilot.evals.substitutes import STRONG_SUBSTITUTE_THETA, SubstitutePair
from promopilot.evals.world import EvalWorld, FittedModels

__all__ = [
    "REPORT_DIR",
    "SCENARIO_DIR",
    "STRONG_SUBSTITUTE_THETA",
    "AcceptRelaxation",
    "Amendment",
    "AsksClarification",
    "DeclaresInfeasible",
    "DiffChanges",
    "EvalReport",
    "EvalWorld",
    "ExcludesRegion",
    "ExpectedProperty",
    "FittedModels",
    "FlagsAssumption",
    "KviResponsePresent",
    "LineOutcome",
    "MeetsClearance",
    "Metric",
    "NoStrongSubstitutesTogether",
    "Oracle",
    "PlanOutcome",
    "RelaxationTouches",
    "ReportPaths",
    "RequestLabels",
    "RunOutcome",
    "RunResult",
    "Scenario",
    "ScenarioGroup",
    "ScenarioResult",
    "SubstitutePair",
    "load_scenario",
    "load_scenarios",
    "render_markdown",
    "run",
    "write_report",
]
