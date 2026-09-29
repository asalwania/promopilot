"""The Critic (AG-04, SPEC §9.6, ADR 0051): deterministic checks first, the LLM second.

`review_attempt` checks a planner attempt's plan with `validate_plan` (hard constraints, ADR
0028) and `review_risks` (over-concentration, heavy cannibalisation, stock-out risk). Both are
deterministic and compute every number. The LLM only rewords each risk finding's template
feedback for the planner: it sees the findings alone, and its wording is kept only when every
number in it is one the finding shows (`check_numeric_grounding`). When it is down, replay has
no cassette, or its answer is blank, misses a finding or cites a number of its own, the template
feedback stays. The LLM is not called when there are no risk findings.

`handoff` decides the route: the attempt's findings go back to the planner agent, at most
`MAX_ATTEMPTS - 1` times, unless the plan is clean, the request is infeasible (only an amended
brief fixes it, AG-06), the default sequence planned it (it would plan the same revision
again), or its findings repeat the previous attempt's exactly (the next attempt would open
with the same findings, ADR 0059). `best_attempt` then picks the plan that goes on to the
Explainer.

Every finding is a `finding` trace event, and the route a `decision` (ADR 0047).
"""

import json
from collections import Counter
from enum import StrEnum
from importlib.resources import files
from typing import Final

import structlog
from pydantic import BaseModel, Field

from promopilot.agents.state import PlanAttempt
from promopilot.agents.trace import emit
from promopilot.domain import (
    CompanyPolicy,
    DecisionMade,
    FindingRaised,
    OpenIssue,
    PlanningRequest,
    RiskFinding,
    SolveStatus,
    Violation,
)
from promopilot.guardrails import (
    RiskThresholds,
    check_numeric_grounding,
    review_risks,
    validate_plan,
)
from promopilot.llm import LLMError, LLMProvider, Message

log = structlog.get_logger(__name__)

MAX_ATTEMPTS: Final = 4
"""Planner attempts per planning round: the first and 3 loop-backs from the Critic (AG-04)."""


class FindingFeedback(BaseModel):
    finding: int = Field(description="The finding's `finding` number in the findings data.")
    feedback: str = Field(description="What the planner should change: one or two sentences.")


class CriticFeedback(BaseModel):
    """What the Critic's LLM writes: actionable feedback for each risk finding."""

    feedback: list[FindingFeedback] = Field(description="One feedback for every finding.")


class Handoff(StrEnum):
    """Why the Critic hands the plan to the Explainer instead of looping back."""

    PLAN_VALID = "plan_valid"
    INFEASIBLE = "infeasible"
    DEFAULT_SEQUENCE = "default_sequence"
    FINDINGS_REPEATED = "findings_repeated"
    CAP_REACHED = "cap_reached"


def critic_prompt() -> str:
    return (files("promopilot.agents") / "prompts" / "critic.md").read_text("utf-8")


async def review_attempt(
    attempt: PlanAttempt,
    *,
    request: PlanningRequest,
    policy: CompanyPolicy,
    thresholds: RiskThresholds,
    llm: LLMProvider,
) -> tuple[OpenIssue, ...]:
    """The attempt's violations, then its risk findings with their feedback."""
    violations = validate_plan(attempt.facts, request, policy)
    risks = review_risks(attempt.plan, attempt.facts, request, thresholds)
    for violation in violations:
        await _found("plan_validation", violation.code.value, violation.message)
    worded = await _worded(risks, llm)
    for finding in worded:
        await _found("risk_review", finding.code.value, finding.message)
    return (*violations, *worded)


def handoff(attempts: tuple[PlanAttempt, ...], *, agent_plans: bool) -> Handoff | None:
    """Why the latest reviewed attempt goes on to the Explainer; None to loop back to the
    Planner with its findings."""
    latest = attempts[-1]
    plan = latest.plan
    if not latest.findings:
        return Handoff.PLAN_VALID
    if plan.relaxation is not None or plan.solver_status is SolveStatus.INFEASIBLE:
        return Handoff.INFEASIBLE
    if not agent_plans or latest.degraded is not None:
        return Handoff.DEFAULT_SEQUENCE
    if len(attempts) > 1 and _same_findings(latest, attempts[-2]):
        return Handoff.FINDINGS_REPEATED
    if len(attempts) >= MAX_ATTEMPTS:
        return Handoff.CAP_REACHED
    return None


def _same_findings(attempt: PlanAttempt, previous: PlanAttempt) -> bool:
    """Whether the two attempts have the same findings, in any order (ADR 0059). A finding is
    what it says: its kind, code, SKU, region, category and message, whose numbers are
    formatted. The Critic's LLM wording of its feedback and its raw numbers are left out."""
    return _found_issues(attempt) == _found_issues(previous)


def _found_issues(attempt: PlanAttempt) -> Counter[tuple[str | None, ...]]:
    return Counter(
        (
            issue.kind,
            issue.code.value,
            issue.sku_id,
            issue.region.value if issue.region else None,
            getattr(issue, "category", None),
            issue.message,
        )
        for issue in attempt.findings
    )


def best_attempt(attempts: tuple[PlanAttempt, ...], *, objective_tolerance: float) -> PlanAttempt:
    """The best feasible plan (ADR 0051 D7, ADR 0078):

    1. the fewest violations;
    2. among those, the attempts whose plan-time objective is within `objective_tolerance`
       (a share) of the highest one's, so fewer risk findings never cost more than that;
    3. among those, the fewest risk findings, then the highest objective.

    A tie goes to the later attempt. An attempt with no objective is never ruled out by it."""
    fewest = min(_counts(attempt)[0] for attempt in attempts)
    candidates = [attempt for attempt in attempts if _counts(attempt)[0] == fewest]
    known = [a.plan.objective for a in candidates if a.plan.objective is not None]
    if known:
        top = max(known)
        floor = top - objective_tolerance * abs(top)
        candidates = [
            attempt
            for attempt in candidates
            if attempt.plan.objective is None or attempt.plan.objective >= floor
        ]
    best = candidates[0]
    for attempt in candidates[1:]:
        if _at_least_as_good(attempt, best):
            best = attempt
    return best


def _at_least_as_good(attempt: PlanAttempt, other: PlanAttempt) -> bool:
    risks, other_risks = _counts(attempt)[1], _counts(other)[1]
    if risks != other_risks:
        return risks < other_risks
    objective, other_objective = attempt.plan.objective, other.plan.objective
    if objective is None or other_objective is None:
        return True
    return objective >= other_objective


def _counts(attempt: PlanAttempt) -> tuple[int, int]:
    violations = [issue for issue in attempt.findings if isinstance(issue, Violation)]
    risks = [issue for issue in attempt.findings if isinstance(issue, RiskFinding)]
    return len(violations), len(risks)


def route_summary(
    handoff: Handoff | None,
    attempts: tuple[PlanAttempt, ...],
    *,
    chosen: PlanAttempt | None = None,
) -> str:
    """The Critic's routing decision in a sentence a promotions manager can read, naming the
    `chosen` attempt when there was more than one."""
    reason = _route_reason(handoff, attempts)
    if chosen is None or len(attempts) == 1:
        return reason
    number = next(n for n, attempt in enumerate(attempts, start=1) if attempt is chosen)
    return f"{reason} Attempt {number} of {len(attempts)} is the best plan and goes on."


def _route_reason(handoff: Handoff | None, attempts: tuple[PlanAttempt, ...]) -> str:
    findings = attempts[-1].findings
    match handoff:
        case None:
            found = "one finding" if len(findings) == 1 else f"{len(findings)} findings"
            return (
                f"The Critic sends attempt {len(attempts)} of {MAX_ATTEMPTS} back to the planner "
                f"with {found} to address."
            )
        case Handoff.PLAN_VALID:
            return "The plan meets every hard constraint and shows no risk above the thresholds."
        case Handoff.INFEASIBLE:
            return (
                "The request is infeasible: the plan goes on with its relaxation, which only an "
                "amended brief can apply."
            )
        case Handoff.DEFAULT_SEQUENCE:
            return (
                "The default sequence planned this revision and would plan it again, so its "
                "findings go to approval as open issues."
            )
        case Handoff.FINDINGS_REPEATED:
            return (
                f"Attempt {len(attempts)} has the same findings as attempt {len(attempts[:-1])}, "
                "so another attempt would plan the same: the best plan goes to approval with "
                "its findings as open issues."
            )
        case Handoff.CAP_REACHED:
            return (
                f"The planner has made {MAX_ATTEMPTS} attempts, so the best plan goes to "
                "approval with its findings as open issues."
            )


async def decide(decision: str, summary: str) -> None:
    """A Critic decision: a `decision` trace event (ADR 0047)."""
    await emit(DecisionMade(decision=decision, summary=summary))


async def _found(source: str, code: str, message: str) -> None:
    """A Critic finding: a `finding` trace event (ADR 0047)."""
    await emit(FindingRaised(source=source, code=code, message=message))


async def _worded(risks: tuple[RiskFinding, ...], llm: LLMProvider) -> tuple[RiskFinding, ...]:
    """The risk findings with the LLM's feedback, or their template feedback when the LLM
    cannot word it."""
    if not risks:
        return ()
    data = [
        {
            "finding": number,
            "code": finding.code.value,
            "message": finding.message,
            "template_feedback": finding.feedback,
        }
        | ({"sku_id": finding.sku_id} if finding.sku_id else {})
        | ({"region": finding.region.value} if finding.region else {})
        | ({"category": finding.category} if finding.category else {})
        for number, finding in enumerate(risks, start=1)
    ]
    messages = [
        Message(role="system", content=critic_prompt()),
        Message(
            role="user",
            content="Risk findings (JSON from PromoPilot's deterministic review):\n"
            f"{json.dumps(data, ensure_ascii=False)}",
        ),
    ]
    try:
        answer = await llm.complete_structured(CriticFeedback, messages)
    except LLMError as error:
        log.warning("critic_feedback_fallback", reason="llm_unavailable", error=str(error))
        return risks
    written = {item.finding: item.feedback.strip() for item in answer.feedback}
    worded = []
    for number, (finding, shown) in enumerate(zip(risks, data, strict=True), start=1):
        text = written.get(number, "")
        if not text or not check_numeric_grounding(text, shown).grounded:
            log.warning("critic_feedback_fallback", reason="invalid_answer", finding=number)
            return risks
        worded.append(finding.model_copy(update={"feedback": text}))
    return tuple(worded)
