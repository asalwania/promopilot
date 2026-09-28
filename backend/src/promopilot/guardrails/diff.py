"""What changed between consecutive plan revisions (AG-05, ADR 0052), computed
deterministically so the Explainer only has to cite it.

Plan lines are matched by (SKU, region), which a plan holds at most once (ADR 0004). A line in
both revisions is changed when its decision differs (mechanism, depth, duration, start week,
target segment or bundle partner); a line whose decision is the same is unchanged, even when
its expected numbers moved because other lines changed around it.
"""

from collections.abc import Callable

from promopilot.domain import (
    LineChange,
    PlanLine,
    PlanningRequest,
    PlanRevision,
    PlanRevisionLine,
    Region,
    RequestChange,
    RevisionDiff,
)
from promopilot.guardrails.formatting import format_percent, format_rupees

DECISION_FIELDS = tuple(name for name in PlanLine.model_fields if name not in {"sku_id", "region"})
"""The plan-line fields that make its decision, in `PlanLine` order."""

_POLICY = "company policy"


def diff_revisions(
    previous: PlanRevision,
    current: PlanRevision,
    *,
    previous_request: PlanningRequest | None = None,
    request: PlanningRequest | None = None,
) -> RevisionDiff:
    """The diff from `previous` to `current`, with the request changes when both requests are
    given. Added lines are in `current`'s plan order, removed ones in `previous`'s."""
    before = {_key(planned): planned for planned in previous.lines}
    after = {_key(planned): planned for planned in current.lines}
    changed = []
    unchanged = 0
    for key, planned in after.items():
        old = before.get(key)
        if old is None:
            continue
        fields = tuple(
            name
            for name in DECISION_FIELDS
            if getattr(old.line, name) != getattr(planned.line, name)
        )
        if fields:
            changed.append(
                LineChange(sku_id=key[0], region=key[1], fields=fields, before=old, after=planned)
            )
        else:
            unchanged += 1
    cost_before = _promo_cost(previous)
    cost_after = _promo_cost(current)
    objective_delta = (
        None
        if previous.objective is None or current.objective is None
        else current.objective - previous.objective
    )
    return RevisionDiff(
        from_revision=previous.number,
        added=tuple(planned for key, planned in after.items() if key not in before),
        removed=tuple(planned for key, planned in before.items() if key not in after),
        changed=tuple(changed),
        unchanged=unchanged,
        objective_before=previous.objective,
        objective_after=current.objective,
        objective_delta=objective_delta,
        promo_cost_before=cost_before,
        promo_cost_after=cost_after,
        promo_cost_delta=cost_after - cost_before,
        request_changes=()
        if previous_request is None or request is None
        else request_changes(previous_request, request),
    )


def request_changes(
    previous: PlanningRequest, current: PlanningRequest
) -> tuple[RequestChange, ...]:
    """Each planning-request field that differs, shown before and after, in field order."""
    changes = []
    for field, show in _REQUEST_FIELDS:
        before, after = show(previous), show(current)
        if before != after:
            changes.append(RequestChange(field=field, before=before, after=after))
    return tuple(changes)


def _key(planned: PlanRevisionLine) -> tuple[str, Region]:
    return planned.line.sku_id, planned.line.region


def _promo_cost(revision: PlanRevision) -> float:
    return sum(planned.promo_cost for planned in revision.lines)


def _listed(values: tuple[str, ...]) -> str:
    return ", ".join(values) if values else "none"


def _optional_percent(value: float | None) -> str:
    return _POLICY if value is None else format_percent(value)


_REQUEST_FIELDS: tuple[tuple[str, Callable[[PlanningRequest], str]], ...] = (
    ("as_of_week", lambda r: f"W{r.as_of_week}"),
    ("scope.regions", lambda r: _listed(tuple(region.value for region in r.scope.regions))),
    ("scope.categories", lambda r: _listed(r.scope.categories)),
    ("scope.sku_ids", lambda r: _listed(r.scope.sku_ids)),
    (
        "promo_window",
        lambda r: f"W{r.promo_window.start_week} to W{r.promo_window.end_week}",
    ),
    ("marketing_budget", lambda r: format_rupees(r.marketing_budget)),
    ("min_margin", lambda r: _optional_percent(r.min_margin)),
    (
        "clearance_targets",
        lambda r: (
            "; ".join(
                f"{target.sku_id} at {format_percent(target.sell_through)}"
                for target in r.clearance_targets
            )
            or "none"
        ),
    ),
    (
        "regional_budget_caps",
        lambda r: (
            "; ".join(
                f"{region.value} {format_rupees(cap)}"
                for region, cap in sorted(r.regional_budget_caps.items())
            )
            or "none"
        ),
    ),
    ("kvi_price_tolerance", lambda r: _optional_percent(r.kvi_price_tolerance)),
    (
        "max_promoted_skus_per_category_per_region",
        lambda r: (
            _POLICY
            if r.max_promoted_skus_per_category_per_region is None
            else str(r.max_promoted_skus_per_category_per_region)
        ),
    ),
)
