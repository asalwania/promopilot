"""Amendments the system writes for the manager: accepting a relaxation (ADR 0044) is an
amendment stating each change exactly, which the Context agent reads like any other
(ADR 0052). Every value is the relaxation's own, shown to the paisa or basis point."""

from promopilot.domain import ConstraintKind, Relaxation, RelaxedConstraint


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
        case ConstraintKind.MARGIN_FLOOR:
            raise ValueError("company policy is never relaxed (ADR 0007)")
