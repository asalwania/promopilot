"""The eval check (`python -m promopilot.evals --check`, ADR 0069): what fails CI's smoke eval.

A report fails the check on what must never regress when the committed cassettes are replayed:

- a run that did not end waiting to approve a plan (it failed, or is still asking);
- a final plan that breaks a hard constraint on its plan-time values (ADR 0012);
- an expected property that does not hold;
- a vague or conflicting scenario that neither asked nor flagged, or an infeasible one not
  declared infeasible with a relaxation and a binding constraint (the 100% targets, #55);
- any request no cassette holds, in any round.

The ratio metrics (plan quality, regret, extraction, grounding, model recovery) are reported
but never fail it: with a handful of scenarios, one scenario moves a share by 20 points, and
their targets are reviewed after the first full run (#58). Fallbacks the recording itself made
are replayed as recorded, and are not problems.
"""

from promopilot.evals.report import ConstraintCheck, EvalReport, RunOutcome, RunResult


def report_problems(report: EvalReport) -> list[str]:
    """Every reason `report` fails the check, one line each; empty when it passes."""
    if not report.scenarios:
        return ["no scenario ran"]
    return [
        f"{scenario.name} run {played.run}: {problem}"
        for scenario in report.scenarios
        for played in scenario.runs
        for problem in _run_problems(played)
    ]


def _run_problems(played: RunResult) -> list[str]:
    found = []
    if played.outcome is RunOutcome.FAILED:
        found.append(f"failed: {played.error}")
    elif played.outcome is RunOutcome.AWAITING_CLARIFICATION:
        found.append(f"ended with no plan, still asking ({', '.join(played.questions_asked)})")
    if played.constraints is ConstraintCheck.FAILED:
        found += [violation.message for violation in played.violations]
    found += [
        f"expected `{result.property}`: {result.detail}"
        for result in played.properties
        if not result.passed
    ]
    clarified = played.clarification
    if clarified is not None and not clarified.passed:
        found.append(f"neither asked about nor flagged {', '.join(clarified.named)}")
    infeasible = played.infeasibility
    if infeasible is not None and not infeasible.passed:
        found.append(infeasible.shortfall)
    if played.cassette_misses:
        count = len(played.cassette_misses)
        requests = "request" if count == 1 else "requests"
        found.append(f"{count} {requests} no cassette holds: {', '.join(played.cassette_misses)}")
    return found
