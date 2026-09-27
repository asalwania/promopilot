"""Applying a relaxation to the planning request it relaxes (ADR 0044).

`solve` finds the smallest change to the brief's constraints that makes an infeasible request
feasible. `relaxed_request` writes those changes back into the request, so the planner (or a
manager's amendment) can plan it again. Only brief values change: company policy is never
relaxed (ADR 0007).
"""

from promopilot.domain import ConstraintKind, PlanningRequest, Relaxation


def relaxed_request(request: PlanningRequest, relaxation: Relaxation) -> PlanningRequest:
    """The request with each of the relaxation's changes applied: a dropped KVI tolerance
    leaves company policy's setting, a dropped clearance target removes it."""
    values = request.model_dump()
    caps = dict(request.regional_budget_caps)
    targets = {target.sku_id: target.sell_through for target in request.clearance_targets}
    for change in relaxation.changes:
        relaxed = change.relaxed
        if change.kind is ConstraintKind.MARKETING_BUDGET:
            values["marketing_budget"] = relaxed
        elif change.kind is ConstraintKind.REGIONAL_BUDGET:
            assert change.region is not None
            assert relaxed is not None
            caps[change.region] = relaxed
        elif change.kind is ConstraintKind.MINIMUM_MARGIN:
            values["min_margin"] = relaxed
        elif change.kind is ConstraintKind.MAX_PROMOTED_SKUS:
            assert relaxed is not None
            values["max_promoted_skus_per_category_per_region"] = round(relaxed)
        elif change.kind is ConstraintKind.KVI_PRICE_TOLERANCE:
            values["kvi_price_tolerance"] = relaxed
        elif change.kind is ConstraintKind.CLEARANCE_TARGET:
            assert change.sku_id is not None
            if relaxed is None:
                targets.pop(change.sku_id, None)
            else:
                targets[change.sku_id] = relaxed
        else:
            raise ValueError(f"{change.kind} is company policy and is never relaxed")
    values["regional_budget_caps"] = caps
    values["clearance_targets"] = [
        {"sku_id": sku_id, "sell_through": share} for sku_id, share in targets.items()
    ]
    return PlanningRequest.model_validate(values)
