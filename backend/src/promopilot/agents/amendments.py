"""Amendments the system writes for the manager, accepted relaxations, and what a decision on
a plan revision may not do.

Accepting a relaxation (ADR 0044) is an amendment whose text states each change exactly, to the
paisa or basis point (ADR 0052 D7). The Context agent's LLM never reads that text: code applies
the relaxation's own values after every reading of the brief, so a change for one SKU never
touches another (ADR 0083).

The API and the cassette recorder apply the same two rules (ADR 0070): an infeasible revision is
never approved (ADR 0046 D10), and only a relaxation that changes something can be accepted."""

from collections.abc import Sequence
from dataclasses import replace

from promopilot.agents.assumptions import ContextReading
from promopilot.agents.state import AcceptedRelaxation
from promopilot.domain import (
    Assumption,
    AssumptionSource,
    CompanyPolicy,
    ConstraintKind,
    PlanningRequest,
    PlanRevision,
    Relaxation,
    RelaxedConstraint,
    SolveStatus,
)
from promopilot.guardrails import plan_limits
from promopilot.optimizer import relaxed_request


def approval_refusal(revision: PlanRevision) -> str | None:
    """Why `revision` cannot be approved: it is infeasible. None when it can."""
    if revision.solver_status is SolveStatus.INFEASIBLE:
        return (
            f"plan revision {revision.number} is infeasible: amend the brief with its "
            "relaxation before approving"
        )
    return None


def acceptable_relaxation(revision: PlanRevision) -> Relaxation | None:
    """The relaxation `revision` offers to accept, or None when it offers no change."""
    relaxation = revision.relaxation
    if relaxation is None or not relaxation.changes:
        return None
    return relaxation


def relaxation_amendment(relaxation: Relaxation) -> str:
    """The amendment that accepts `relaxation`, one clause per change."""
    clauses = [_clause(change) for change in relaxation.changes]
    return f"Accept the smallest relaxation: {'; '.join(clauses)}."


def _clause(change: RelaxedConstraint) -> str:
    relaxed = change.relaxed
    match change.kind:
        case ConstraintKind.MARKETING_BUDGET:
            return f"raise the marketing budget to ₹{relaxed:,.2f}"
        case ConstraintKind.REGIONAL_BUDGET:
            region = "" if change.region is None else f" for {change.region.value}"
            return f"raise the budget cap{region} to ₹{relaxed:,.2f}"
        case ConstraintKind.MINIMUM_MARGIN:
            return f"lower the minimum margin to {relaxed:.2%}"
        case ConstraintKind.MAX_PROMOTED_SKUS:
            return f"raise the cap on promoted SKUs per category and region to {relaxed:.0f}"
        case ConstraintKind.KVI_PRICE_TOLERANCE:
            if relaxed is None:
                return "turn off the KVI price tolerance"
            return f"set the KVI price tolerance to {relaxed:.2%}"
        case ConstraintKind.CLEARANCE_TARGET:
            if relaxed is None:
                return f"drop the clearance target for {change.sku_id}"
            return f"lower the clearance target for {change.sku_id} to {relaxed:.2%} sell-through"
        case ConstraintKind.MARGIN_FLOOR | ConstraintKind.STRONG_SUBSTITUTES:
            raise ValueError("company policy is never relaxed (ADR 0007)")


def apply_accepted(
    reading: ContextReading, accepted: Sequence[AcceptedRelaxation], policy: CompanyPolicy
) -> ContextReading:
    """The reading with each accepted relaxation applied, oldest first (ADR 0083).

    A change applies while the reading still gives the value it relaxed from: a later amendment
    that states another value for the field wins. Each applied change rewrites its field's
    assumption; a clearance target is per SKU, so its assumption follows the brief's instead.
    A reading still asking questions is returned as it is.
    """
    request = reading.request
    if request is None or not accepted:
        return reading
    assumptions = list(reading.assumptions)
    for acceptance in accepted:
        changes = tuple(
            change
            for change in acceptance.relaxation.changes
            if _still_reads(request, change, policy)
        )
        if not changes:
            continue
        request = relaxed_request(
            request, acceptance.relaxation.model_copy(update={"changes": changes})
        )
        for change in changes:
            _assume(assumptions, request, change, acceptance.revision_number)
    return replace(reading, request=request, assumptions=tuple(assumptions))


def _still_reads(
    request: PlanningRequest, change: RelaxedConstraint, policy: CompanyPolicy
) -> bool:
    """Whether `request` still holds the value `change` relaxed from, as the optimiser read it
    (the rules `plan_limits` applies, for the fields company policy bounds)."""
    limits = plan_limits(request, policy)
    held: float | None
    match change.kind:
        case ConstraintKind.MARKETING_BUDGET:
            held = request.marketing_budget
        case ConstraintKind.REGIONAL_BUDGET:
            held = (
                None if change.region is None else request.regional_budget_caps.get(change.region)
            )
        case ConstraintKind.MINIMUM_MARGIN:
            held = limits.min_margin
        case ConstraintKind.MAX_PROMOTED_SKUS:
            held = limits.max_promoted_skus
        case ConstraintKind.KVI_PRICE_TOLERANCE:
            held = limits.kvi_price_tolerance
        case ConstraintKind.CLEARANCE_TARGET:
            wanted = {t.sku_id: t.sell_through for t in request.clearance_targets}
            held = wanted.get(str(change.sku_id))
        case ConstraintKind.MARGIN_FLOOR | ConstraintKind.STRONG_SUBSTITUTES:
            raise ValueError("company policy is never relaxed (ADR 0007)")
    # The relaxation copied `current` from the request it relaxed, so an unchanged reading
    # holds exactly that value.
    return held is not None and held == change.current


_FIELDS = {
    ConstraintKind.MARKETING_BUDGET: "marketing_budget",
    ConstraintKind.REGIONAL_BUDGET: "regional_budget_caps",
    ConstraintKind.MINIMUM_MARGIN: "min_margin",
    ConstraintKind.MAX_PROMOTED_SKUS: "max_promoted_skus_per_category_per_region",
    ConstraintKind.KVI_PRICE_TOLERANCE: "kvi_price_tolerance",
    ConstraintKind.CLEARANCE_TARGET: "clearance_targets",
}
"""The planning-request field, and its assumption's, that each kind of change relaxes."""


def _assume(
    assumptions: list[Assumption],
    request: PlanningRequest,
    change: RelaxedConstraint,
    revision_number: int,
) -> None:
    accepted = f"The accepted relaxation of plan revision {revision_number}"
    field = _FIELDS[change.kind]
    if change.kind is ConstraintKind.CLEARANCE_TARGET:
        sku_id, asked = change.sku_id, f"{change.current:.2%}"
        if change.relaxed is None:
            value = f"none for {sku_id}"
            note = f"{accepted}: it drops the {asked} the brief asks for {sku_id}."
        else:
            value = f"{change.relaxed:.2%} sell-through for {sku_id}"
            note = f"{accepted}: it replaces the {asked} the brief asks for {sku_id}."
        assumptions.append(_stated(field, value, note))
        return
    match change.kind:
        case ConstraintKind.MARKETING_BUDGET:
            value = _rupees(request.marketing_budget)
        case ConstraintKind.REGIONAL_BUDGET:
            caps = request.regional_budget_caps.items()
            value = ", ".join(f"{region.value} {_rupees(cap)}" for region, cap in caps)
        case ConstraintKind.MINIMUM_MARGIN | ConstraintKind.KVI_PRICE_TOLERANCE:
            share = getattr(request, field)
            value = "off" if share is None else f"{share:.2%}"
        case _:
            value = str(request.max_promoted_skus_per_category_per_region)
    rewritten = _stated(field, value, f"{accepted}.")
    for n, assumption in enumerate(assumptions):
        if assumption.field == field:
            assumptions[n] = rewritten
            return
    assumptions.append(rewritten)


def _stated(field: str, value: str, note: str) -> Assumption:
    return Assumption(
        field=field, value=value, source=AssumptionSource.BRIEF, confidence=1.0, note=note
    )


def _rupees(amount: float) -> str:
    return f"₹{amount:,.2f}".removesuffix(".00")
