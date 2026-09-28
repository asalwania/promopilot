"""The eval report (SPEC §12.3, ADR 0056): every metric against its SPEC §12.2 target, and each
scenario's runs, written as timestamped JSON and Markdown with `latest` copies.

The JSON is `EvalReport` as it is, so `GET /api/evals/latest` (#57) can serve it and the
frontend types can be generated from it.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from promopilot.domain import (
    ExplanationSource,
    FallbackReason,
    Region,
    SessionUsage,
    SolveStatus,
    Violation,
)

REPORT_DIR = Path("evals/reports")
"""Where `make eval` writes its reports, relative to backend/ (gitignored)."""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class RunOutcome(StrEnum):
    """How a scenario's session ended."""

    PLANNED = "planned"
    """It waits for approval of its final plan revision, every amendment applied."""
    AWAITING_CLARIFICATION = "awaiting_clarification"
    """It asked a question the scenario does not answer, or kept asking: no final plan."""
    FAILED = "failed"
    """An error stopped it."""


class ConstraintCheck(StrEnum):
    """The final plan revision's hard constraints on its plan-time values (ADR 0012)."""

    PASSED = "passed"
    FAILED = "failed"
    INFEASIBLE = "infeasible"
    """Not scored: the request is infeasible, which infeasibility handling scores (#55)."""
    NO_PLAN = "no_plan"
    """Not scored: the session ended without a final plan."""


class Breach(StrEnum):
    """A constraint the plan's true outcome breaks, by the oracle (ADR 0012)."""

    PROMO_COST_OVER_BUDGET = "promo_cost_over_budget"
    MARGIN_BELOW_MINIMUM = "margin_below_minimum"
    DEMAND_OVER_STOCK = "demand_over_stock"


class OracleScore(_Frozen):
    """The final plan's true expected outcome (ADR 0011, ADR 0017)."""

    incremental_profit: float
    clearance_value: float
    promo_cost: float
    blended_margin: float | None
    stock_capped_lines: int
    breaches: tuple[Breach, ...]


class RevisionSummary(_Frozen):
    number: int
    lines: int
    regions: tuple[Region, ...]
    """The regions with a plan line, in plan order."""
    solver_status: SolveStatus | None
    objective: float | None
    promo_cost: float
    """Expected, on the plan's own numbers."""
    marketing_budget: float
    """The final planning request's budget."""


class PropertyResult(_Frozen):
    property: str
    passed: bool
    detail: str


class FieldMatch(_Frozen):
    """One labelled planning-request field against what the final request reads (#55)."""

    field: str
    """The label's name, as `RequestLabels` has it."""
    expected: str
    got: str | None
    """None when the session ended with no planning request."""
    matched: bool


class ClarificationCheck(_Frozen):
    """Whether a vague or conflicting scenario's session asked about, or flagged, a field the
    scenario names (#55)."""

    named: tuple[str, ...]
    """The fields its `asks_clarification` and `flags_assumption` properties name."""
    asked: tuple[str, ...]
    """The question ids asked about a named field."""
    flagged: tuple[str, ...]
    """The named fields the final reading flags."""
    passed: bool


class InfeasibilityCheck(_Frozen):
    """Whether an infeasible scenario's final revision says so, names what binds and proposes
    a relaxation (AG-06, #55)."""

    revision: int | None
    """The final revision's number; None with no final plan."""
    declared: bool
    relaxation: bool
    binding_named: bool
    passed: bool


class ExplainerRun(_Frozen):
    """One run of the Explainer: the explanation a plan revision waited for approval with."""

    revision: int
    source: ExplanationSource
    fallback_reason: FallbackReason | None


class RunResult(_Frozen):
    run: int
    """1-based."""
    outcome: RunOutcome
    error: str | None = None
    route: tuple[str, ...] = ()
    """The graph nodes the session ran, with the interrupts it paused at."""
    questions_asked: tuple[str, ...] = ()
    """The id of every question the Context agent asked, in order."""
    amendments_applied: int = 0
    fallbacks: tuple[str, ...] = ()
    """What the final round did without the LLM: `context`, `planner` or `explainer`, each
    with its reason."""
    revision: RevisionSummary | None = None
    constraints: ConstraintCheck = ConstraintCheck.NO_PLAN
    violations: tuple[Violation, ...] = ()
    oracle: OracleScore | None = None
    """None when the constraints are not scored."""
    properties: tuple[PropertyResult, ...] = ()
    duration_s: float = 0.0
    extraction: tuple[FieldMatch, ...] = ()
    """Each labelled field against the final planning request (#55)."""
    flagged: tuple[str, ...] = ()
    """The fields whose assumption the final reading flags."""
    clarification: ClarificationCheck | None = None
    """Only for a vague or conflicting scenario."""
    unneeded_asks: tuple[str, ...] = ()
    """Questions asked that the scenario does not expect, outside the vague group."""
    infeasibility: InfeasibilityCheck | None = None
    """Only for an infeasible-constraints scenario."""
    explanations: tuple[ExplainerRun, ...] = ()
    """Every Explainer run, in order: one per plan revision that waited for approval."""
    session_s: float = 0.0
    """The session's wall-clock time, from the brief to its end, without fitting models."""
    usage: SessionUsage = SessionUsage()
    """The sum of the session's token-usage trace events (ADR 0047)."""

    @property
    def passed(self) -> bool:
        return (
            self.outcome is not RunOutcome.FAILED
            and self.constraints is not ConstraintCheck.FAILED
            and all(result.passed for result in self.properties)
        )


class ScenarioResult(_Frozen):
    name: str
    group: str
    as_of_week: int
    seed: int
    runs: tuple[RunResult, ...]
    passed: bool
    """Every run ran, kept its hard constraints and had every expected property."""


class Metric(_Frozen):
    name: str
    label: str
    value: float | None
    """A share from 0 to 1, or a P50 in `unit`; None when nothing was scored."""
    count: int
    """How many of `of` count towards the value."""
    of: int
    """0 when the value is not a share of counted items (a model's own holdout WAPE)."""
    target: float | None = None
    """SPEC §12.2's target; None for a reported metric."""
    direction: Literal["at_least", "at_most"] | None = None
    passed: bool | None = None
    """None for a reported metric, or when nothing was scored."""
    breakdown: dict[str, int] = {}
    unit: Literal["share", "seconds", "rupees"] = "share"
    """What `value` and `target` are in: a share from 0 to 1, or a P50 in seconds or rupees."""
    aim: float | None = None
    """What a reported metric aims for, in `direction` and `unit`, never judged (SPEC §12.2)."""


class EvalReport(_Frozen):
    generated_at: datetime
    provider: str
    world_seed: int
    runs_per_scenario: int
    planning_settings: dict[str, Any]
    """The environment's planning settings (ADR 0054); each scenario's seed replaces the
    optimiser's and the simulation's."""
    metrics: tuple[Metric, ...]
    scenarios: tuple[ScenarioResult, ...]

    def comparable(self) -> dict[str, Any]:
        """The report without what varies from one identical run to the next: when it was
        generated and how long each run took."""
        dumped = self.model_dump(mode="json", exclude={"generated_at"})
        for metric in dumped["metrics"]:
            if metric["unit"] == "seconds":
                metric.pop("value")
                metric["breakdown"] = {}
        for scenario in dumped["scenarios"]:
            for run in scenario["runs"]:
                run.pop("duration_s")
                run.pop("session_s")
        return dumped


# ---------------------------------------------------------------- writing


@dataclass(frozen=True)
class ReportPaths:
    json: Path
    markdown: Path
    latest_json: Path
    latest_markdown: Path


def write_report(report: EvalReport, directory: Path) -> ReportPaths:
    """`<UTC timestamp>.json` and `.md` in `directory`, and the same as `latest.json` and
    `latest.md`."""
    directory.mkdir(parents=True, exist_ok=True)
    stamp = report.generated_at.strftime("%Y%m%dT%H%M%SZ")
    body, markdown = report.model_dump_json(indent=2) + "\n", render_markdown(report)
    paths = ReportPaths(
        json=directory / f"{stamp}.json",
        markdown=directory / f"{stamp}.md",
        latest_json=directory / "latest.json",
        latest_markdown=directory / "latest.md",
    )
    for path, text in (
        (paths.json, body),
        (paths.markdown, markdown),
        (paths.latest_json, body),
        (paths.latest_markdown, markdown),
    ):
        path.write_text(text, encoding="utf-8", newline="\n")
    return paths


def render_markdown(report: EvalReport) -> str:
    runs = sum(len(scenario.runs) for scenario in report.scenarios)
    lines = [
        "# PromoPilot eval report",
        "",
        f"Generated {report.generated_at.isoformat()} with the `{report.provider}` provider on "
        f"the seed-{report.world_seed} world: {len(report.scenarios)} scenarios, "
        f"{report.runs_per_scenario} run(s) each, {runs} sessions.",
        "",
        "## Metrics",
        "",
        "| Metric | Value | Target | Result |",
        "|---|---|---|---|",
    ]
    for metric in report.metrics:
        value = format_value(metric)
        counted = f" ({metric.count} of {metric.of})" if metric.of else ""
        lines.append(
            f"| {metric.label} | {value}{counted} | {_target(metric)} | {_result(metric.passed)} |"
        )
    breakdowns = [m for m in report.metrics if m.breakdown]
    if breakdowns:
        lines.append("")
        for metric in breakdowns:
            parts = ", ".join(f"{key} {count}" for key, count in metric.breakdown.items())
            lines.append(f"- {metric.label}: {parts}")
    lines += [
        "",
        "## Scenarios",
        "",
        "| Scenario | Group | Run | Outcome | Plan | Constraints | Oracle breaches "
        "| Properties | Result |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for scenario in report.scenarios:
        for run in scenario.runs:
            lines.append(
                f"| {scenario.name} | {scenario.group} | {run.run} | {run.outcome.value} "
                f"| {_plan(run.revision)} | {run.constraints.value} | {_breaches(run.oracle)} "
                f"| {sum(p.passed for p in run.properties)}/{len(run.properties)} "
                f"| {_result(run.passed)} |"
            )
    lines += [
        "",
        "## Agent behaviour",
        "",
        "| Scenario | Run | Extraction | Asked | Flagged | Explainer | Session | Cost |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for scenario in report.scenarios:
        for run in scenario.runs:
            lines.append(f"| {scenario.name} | {run.run} | {_behaviour(run)} |")
    failures = [(scenario.name, run) for scenario in report.scenarios for run in scenario.runs]
    details = [line for name, run in failures for line in _failures(name, run)]
    lines += ["", "## Failures", ""]
    lines += details or ["None."]
    return "\n".join(lines) + "\n"


def format_value(metric: Metric) -> str:
    """A metric's value in its unit: a share as a percentage, a P50 in seconds or rupees."""
    return "n/a" if metric.value is None else format_amount(metric, metric.value)


def format_amount(metric: Metric, amount: float, *, share_digits: int = 1) -> str:
    """An amount in the metric's unit, such as its value, target or aim."""
    if metric.unit == "seconds":
        return f"{amount:.1f} s"
    if metric.unit == "rupees":
        return f"₹{amount:,.2f}"
    return f"{amount:.{share_digits}%}"


def _behaviour(run: RunResult) -> str:
    extraction = (
        f"{sum(match.matched for match in run.extraction)}/{len(run.extraction)}"
        if run.extraction
        else "—"
    )
    explained = ", ".join(
        "llm"
        if explanation.fallback_reason is None
        else f"template ({explanation.fallback_reason.value})"
        for explanation in run.explanations
    )
    cost = f"₹{run.usage.cost_inr:,.2f}, {run.usage.calls} calls"
    if run.usage.unpriced_models:
        cost += f" (unpriced: {', '.join(run.usage.unpriced_models)})"
    return " | ".join(
        (
            extraction,
            ", ".join(run.questions_asked) or "—",
            ", ".join(run.flagged) or "—",
            explained or "—",
            f"{run.session_s:.1f} s",
            cost,
        )
    )


def _target(metric: Metric) -> str:
    sign = "≥" if metric.direction == "at_least" else "≤"
    if metric.target is None:
        if metric.aim is None:
            return "report"
        return f"report (aim {sign} {format_amount(metric, metric.aim, share_digits=0)})"
    return f"{sign} {format_amount(metric, metric.target, share_digits=0)}"


def _result(passed: bool | None) -> str:
    return "—" if passed is None else ("pass" if passed else "**fail**")


def _plan(revision: RevisionSummary | None) -> str:
    if revision is None:
        return "—"
    status = revision.solver_status.value if revision.solver_status else "?"
    return f"rev {revision.number}: {revision.lines} lines, {status}"


def _breaches(oracle: OracleScore | None) -> str:
    if oracle is None:
        return "—"
    return ", ".join(breach.value for breach in oracle.breaches) or "none"


def _failures(name: str, run: RunResult) -> list[str]:
    where = f"- **{name}** run {run.run}:"
    found = []
    if run.error is not None:
        found.append(f"{where} {run.outcome.value}: {run.error}")
    elif run.outcome is RunOutcome.AWAITING_CLARIFICATION:
        asked = ", ".join(run.questions_asked)
        found.append(f"{where} still asking ({asked})")
    found += [f"{where} {violation.message}" for violation in run.violations]
    found += [
        f"{where} expected `{result.property}`: {result.detail}"
        for result in run.properties
        if not result.passed
    ]
    found += [
        f"{where} read `{match.field}` as {match.got or 'nothing'}, labelled {match.expected}"
        for match in run.extraction
        if not match.matched
    ]
    clarified = run.clarification
    if clarified is not None and not clarified.passed:
        found.append(f"{where} neither asked about nor flagged {', '.join(clarified.named)}")
    infeasible = run.infeasibility
    if infeasible is not None and not infeasible.passed:
        if infeasible.revision is None:
            found.append(f"{where} no final plan revision to declare infeasible")
        else:
            missing = [
                part
                for part, ok in (
                    ("is not declared infeasible", infeasible.declared),
                    ("proposes no relaxation", infeasible.relaxation),
                    ("names no binding constraint", infeasible.binding_named),
                )
                if not ok
            ]
            found.append(f"{where} revision {infeasible.revision} {' and '.join(missing)}")
    return found
