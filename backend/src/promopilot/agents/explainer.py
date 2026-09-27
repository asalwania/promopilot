"""The template Explainer (ADR 0046): a rationale per plan line and a plan summary written
only from the plan revision's own numbers, so it always passes numeric grounding (ADR 0028).

Money is shown in whole rupees and units as whole numbers, rounded to the nearest one, so every
number is within the rounding its text shows. The LLM Explainer with this template as its
fallback is #49.
"""

from promopilot.agents.state import Explanations
from promopilot.domain import (
    ConstraintKind,
    Mechanism,
    PlanRevision,
    PlanRevisionLine,
    SolveStatus,
    Violation,
)

MECHANISMS = {
    Mechanism.PCT_OFF: "% off",
    Mechanism.FIXED_PRICE: "fixed price",
    Mechanism.BOGO: "buy one get one",
    Mechanism.BUNDLE: "bundle",
}


def template_explanations(
    revision: PlanRevision, open_issues: tuple[Violation, ...] = ()
) -> Explanations:
    return Explanations(
        summary=_summary(revision, open_issues),
        lines=tuple(_rationale(planned) for planned in revision.lines),
    )


def _rationale(planned: PlanRevisionLine) -> str:
    line = planned.line
    partner = "" if line.bundle_partner_sku_id is None else f" with {line.bundle_partner_sku_id}"
    weeks = "week" if line.duration_weeks == 1 else "weeks"
    return (
        f"{line.sku_id} in {line.region.value}: {MECHANISMS[line.mechanism]}{partner} at "
        f"{line.depth_pct}% for {line.duration_weeks} {weeks} from W{line.start_week}, for "
        f"{line.target_segment.value}. Expected {_whole(planned.expected_units)} units, promo "
        f"cost {_rupees(planned.promo_cost)}, expected incremental profit "
        f"{_rupees(planned.expected_incremental_profit)}."
    )


def _summary(revision: PlanRevision, open_issues: tuple[Violation, ...]) -> str:
    parts = [f"Plan revision {revision.number}."]
    status = revision.solver_status
    if status is SolveStatus.INFEASIBLE:
        parts.append(
            "Infeasible: no plan reaches every clearance target within the brief's "
            "constraints, so this is the closest plan."
        )
    elif not revision.lines:
        parts.append("No promo option pays for itself within the brief's constraints.")
    elif status is SolveStatus.OPTIMAL:
        parts.append("The optimiser proved this plan the most profitable within the constraints.")
    else:
        parts.append(
            "The optimiser found this plan within its time limit, without proving it best."
        )
    if revision.objective is not None and revision.lines:
        parts.append(f"Its objective is {_rupees(revision.objective)}.")
    binding = sorted({_kind(constraint.kind) for constraint in revision.binding_constraints})
    if binding:
        parts.append(f"Binding constraints: {', '.join(binding)}.")
    relaxation = revision.relaxation
    if relaxation is not None and relaxation.changes:
        changed = sorted({_kind(change.kind) for change in relaxation.changes})
        parts.append(f"The smallest relaxation changes: {', '.join(changed)}.")
        if relaxation.policy_binds:
            parts.append("Company policy binds: no change to the brief alone reaches the targets.")
    if open_issues:
        codes = sorted({issue.code.value for issue in open_issues})
        parts.append(f"Open issues the critic found: {', '.join(codes)}.")
    return " ".join(parts)


def _kind(kind: ConstraintKind) -> str:
    return kind.value.replace("_", " ")


def _whole(amount: float) -> str:
    return f"{round(amount):,}"


def _rupees(amount: float) -> str:
    """Whole rupees with Indian digit grouping (₹1,50,000; -₹13,813)."""
    whole = round(abs(amount))
    digits = str(whole)
    head, tail = digits[:-3], digits[-3:]
    groups: list[str] = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    grouped = ",".join([*groups, tail]) if groups else tail
    return f"{'-' if amount < 0 and whole else ''}₹{grouped}"
