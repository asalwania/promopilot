"""Strong true substitutes, and whether a plan promotes two of them together (#56, ADR 0065).

The heavy-cannibalisation scenarios expect `no_strong_substitutes_together`. A pair of SKUs is a
**strong substitute** when the ground truth makes it a substitute pair and the larger of its two
directed cross-price effects θ is at least `STRONG_SUBSTITUTE_THETA`. Two SKUs are **promoted
together** when plan lines promote both (a BUNDLE promotes its partner too) in the same region,
with at least one common promo week and a common target segment. These are the conditions under
which the pairwise cannibalisation term is not zero (ADR 0033).

It reads the ground truth, so it lives in `promopilot.evals`.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import pandas as pd

from promopilot.datagen.truth import CrossEffect
from promopilot.domain import PlanLine, PlanRevision, Region, Scope, TargetSegment
from promopilot.evals.report import PropertyResult
from promopilot.evals.scenarios import NoStrongSubstitutesTogether

STRONG_SUBSTITUTE_THETA = 0.5
"""At θ = 0.5, a 20% price cut on one SKU costs the other about 10.6% of its units."""


@dataclass(frozen=True)
class SubstitutePair:
    """A true substitute pair, and the larger of its two directed θ."""

    first: str
    second: str
    theta: float


def strong_substitutes(
    substitute_pairs: Iterable[tuple[str, str]],
    cross_effects: Iterable[CrossEffect],
    threshold: float = STRONG_SUBSTITUTE_THETA,
) -> tuple[SubstitutePair, ...]:
    """The true substitute pairs whose larger directed θ is at least `threshold`, in the
    ground truth's order."""
    theta = {(effect.sku_id, effect.other_sku_id): effect.theta for effect in cross_effects}
    strong = []
    for first, second in substitute_pairs:
        larger = max(theta.get((first, second), 0.0), theta.get((second, first), 0.0))
        if larger >= threshold:
            strong.append(SubstitutePair(first=first, second=second, theta=larger))
    return tuple(strong)


def strong_in_scope(
    pairs: Sequence[SubstitutePair], products: pd.DataFrame, scope: Scope
) -> tuple[SubstitutePair, ...]:
    """The pairs whose SKUs are both in the scope's categories, and among its named SKUs when it
    names any."""
    in_categories = products[products["category"].isin(scope.categories)]["sku_id"]
    skus = set(in_categories)
    if scope.sku_ids:
        skus &= set(scope.sku_ids)
    return tuple(pair for pair in pairs if pair.first in skus and pair.second in skus)


def promoted_together(pair: SubstitutePair, lines: Sequence[PlanLine]) -> tuple[Region, ...]:
    """The regions in which the plan promotes both SKUs of the pair together, in order of first
    appearance."""
    regions: dict[Region, None] = {}
    for first in lines:
        if pair.first not in first.skus:
            continue
        for second in lines:
            if pair.second in second.skus and _overlap(first, second):
                regions[first.region] = None
    return tuple(regions)


def check_no_strong_substitutes(
    prop: NoStrongSubstitutesTogether,
    revision: PlanRevision | None,
    substitutes: Sequence[SubstitutePair],
) -> PropertyResult:
    """Whether the final revision promotes none of the strong pairs in scope together. It fails
    with no final revision, and when the scope has no strong pair, since it then tests nothing."""
    described = prop.describe()
    if revision is None:
        return PropertyResult(property=described, passed=False, detail="no final plan revision")
    if not substitutes:
        return PropertyResult(
            property=described,
            passed=False,
            detail="no strong substitute pair in scope, so nothing is tested",
        )
    lines = [planned.line for planned in revision.lines]
    together = [
        f"{pair.first} and {pair.second} (θ {pair.theta:.2f}) together in "
        f"{', '.join(region.value for region in regions)}"
        for pair in substitutes
        if (regions := promoted_together(pair, lines))
    ]
    if together:
        detail = f"revision {revision.number} promotes {'; '.join(together)}"
        return PropertyResult(property=described, passed=False, detail=detail)
    return PropertyResult(
        property=described,
        passed=True,
        detail=f"revision {revision.number} promotes none of the {len(substitutes)} strong "
        "substitute pairs in scope together",
    )


def _overlap(first: PlanLine, second: PlanLine) -> bool:
    if first.region is not second.region:
        return False
    first_weeks = range(first.start_week, first.start_week + first.duration_weeks)
    second_weeks = range(second.start_week, second.start_week + second.duration_weeks)
    if not set(first_weeks) & set(second_weeks):
        return False
    everyone = TargetSegment.ALL_CUSTOMERS
    return everyone in (first.target_segment, second.target_segment) or (
        first.target_segment is second.target_segment
    )
