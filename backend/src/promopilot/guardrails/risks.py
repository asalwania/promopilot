"""The Critic's risk review (AG-04, SPEC §9.6, ADR 0051): over-concentration, heavy
cannibalisation and stock-out risk, found deterministically on a plan's own tool outputs.

A plan that breaks no hard constraint can still be risky. `review_risks` flags:

- **over-concentration**: one plan line taking more than `line_spend_share` of the plan's promo
  spend (only checked when the plan has enough lines for none to need that much), or one
  category or region taking more than `group_spend_share` when the scope has more than one;
- **heavy cannibalisation**: a plan line whose substitutes lose at least
  `cannibalisation_share` of its incremental profit (lines with a positive incremental profit;
  the others are in the plan for their halo or clearance value);
- **stock-out risk**: a plan line that runs out of stock in at least `stockout_probability` of
  the simulation's runs.

Each finding carries a message with the numbers that show it, and template feedback naming the
planner's levers. Every number the feedback cites is one its message shows, so the LLM that
rewords it (`promopilot.agents`) is grounded against the findings alone.
"""

from collections import defaultdict
from collections.abc import Iterable
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from promopilot.domain import (
    MechanismOption,
    PlanningRequest,
    PlanRevision,
    PlanRevisionLine,
    Region,
    RiskCode,
    RiskFinding,
)
from promopilot.guardrails.formatting import format_percent, format_rupees
from promopilot.guardrails.validation import PlanFacts

_EPSILON: Final = 1e-9


class RiskThresholds(BaseModel):
    """When the risk review flags a plan (`CRITIC_*` settings)."""

    model_config = ConfigDict(frozen=True)

    line_spend_share: float = Field(default=0.25, gt=0, le=1)
    """A plan line above this share of the plan's promo spend is over-concentrated."""
    group_spend_share: float = Field(default=0.80, gt=0, le=1)
    """A category or region above this share, when the scope has more than one, is too."""
    cannibalisation_share: float = Field(default=0.50, gt=0)
    """Cannibalisation at or above this share of a line's incremental profit is heavy."""
    stockout_probability: float = Field(default=0.20, gt=0, le=1)
    """A line that runs out in at least this share of the simulated runs is a stock-out risk."""


def review_risks(
    revision: PlanRevision,
    facts: PlanFacts,
    request: PlanningRequest,
    thresholds: RiskThresholds,
) -> tuple[RiskFinding, ...]:
    """The plan's risks: over-concentration (lines, then categories, then regions), heavy
    cannibalisation, then stock-out risk, each in plan order; () if none."""
    return (
        *_concentration(facts, request, thresholds),
        *_cannibalisation(revision.lines, thresholds.cannibalisation_share),
        *_stockouts(revision, thresholds.stockout_probability),
    )


def _concentration(
    facts: PlanFacts, request: PlanningRequest, thresholds: RiskThresholds
) -> list[RiskFinding]:
    total = sum(fact.promo_cost for fact in facts.lines)
    if total <= 0:
        return []
    findings = []
    limit = thresholds.line_spend_share
    # With fewer than 1 / limit lines, one of them must take more than the limit.
    if len(facts.lines) * limit >= 1 - _EPSILON:
        for fact in facts.lines:
            share = fact.promo_cost / total
            if share <= limit + _EPSILON:
                continue
            sku_id, region = fact.line.sku_id, fact.line.region
            findings.append(
                RiskFinding(
                    code=RiskCode.OVER_CONCENTRATION,
                    message=(
                        f"{sku_id} in {region}: its promo cost {format_rupees(fact.promo_cost)} "
                        f"is {format_percent(share)} of the plan's promo spend "
                        f"{format_rupees(total)}, above the {format_percent(limit)} limit for "
                        "one plan line"
                    ),
                    feedback=(
                        f"Spread the promo spend: give {sku_id} in {region} a shallower or "
                        f"cheaper promotion, or leave {sku_id} out of generate_candidates' "
                        f"sku_ids, so no plan line takes over {format_percent(limit)} of it."
                    ),
                    sku_id=sku_id,
                    region=region,
                    actual=share,
                    limit=limit,
                )
            )
    limit = thresholds.group_spend_share
    if len(request.scope.categories) > 1:
        by_category = _spend((fact.anchor.category, fact.promo_cost) for fact in facts.lines)
        findings += [
            RiskFinding(
                code=RiskCode.OVER_CONCENTRATION,
                message=(
                    f"{category} takes {format_percent(spent / total)} of the plan's promo "
                    f"spend ({format_rupees(spent)} of {format_rupees(total)}), above the "
                    f"{format_percent(limit)} limit for one category of several in scope"
                ),
                feedback=(
                    f"Balance the plan across categories: set a lower "
                    f"max_promoted_skus_per_category_per_region, or narrow generate_candidates' "
                    f"sku_ids in {category}, so {category} takes at most "
                    f"{format_percent(limit)} of the spend."
                ),
                category=category,
                actual=spent / total,
                limit=limit,
            )
            for category in request.scope.categories
            if (spent := by_category.get(category, 0.0)) / total > limit + _EPSILON
        ]
    if len(request.scope.regions) > 1:
        by_region = _spend((fact.line.region, fact.promo_cost) for fact in facts.lines)
        findings += [
            RiskFinding(
                code=RiskCode.OVER_CONCENTRATION,
                message=(
                    f"{region} takes {format_percent(spent / total)} of the plan's promo spend "
                    f"({format_rupees(spent)} of {format_rupees(total)}), above the "
                    f"{format_percent(limit)} limit for one region of several in scope"
                ),
                feedback=(
                    f"Balance the plan across regions: add a lower regional budget cap for "
                    f"{region}, so it takes at most {format_percent(limit)} of the spend."
                ),
                region=region,
                actual=spent / total,
                limit=limit,
            )
            for region in request.scope.regions
            if (spent := by_region.get(region, 0.0)) / total > limit + _EPSILON
        ]
    return findings


def _spend[K: str | Region](amounts: Iterable[tuple[K, float]]) -> dict[K, float]:
    spent: defaultdict[K, float] = defaultdict(float)
    for key, amount in amounts:
        spent[key] += amount
    return dict(spent)


def _cannibalisation(lines: Iterable[PlanRevisionLine], limit: float) -> list[RiskFinding]:
    findings = []
    for planned in lines:
        option = _chosen(planned)
        if option is None or option.incremental_profit <= 0:
            continue
        share = option.cannibalised_profit / option.incremental_profit
        if share < limit - _EPSILON:
            continue
        sku_id, region = planned.line.sku_id, planned.line.region
        findings.append(
            RiskFinding(
                code=RiskCode.HEAVY_CANNIBALISATION,
                message=(
                    f"{sku_id} in {region}: the cannibalisation of its substitutes "
                    f"{format_rupees(option.cannibalised_profit)} is {format_percent(share)} of "
                    f"its incremental profit {format_rupees(option.incremental_profit)}, at or "
                    f"above the {format_percent(limit)} limit"
                ),
                feedback=(
                    f"{sku_id} in {region} mostly takes sales from its own substitutes: try "
                    f"another mechanism or a shallower depth for it (compare_mechanisms), or "
                    f"leave {sku_id} out of generate_candidates' sku_ids."
                ),
                sku_id=sku_id,
                region=region,
                actual=share,
                limit=limit,
            )
        )
    return findings


def _chosen(planned: PlanRevisionLine) -> MechanismOption | None:
    """The plan line's own option, as its mechanism comparison shows it (ADR 0041)."""
    for outcome in planned.mechanism_comparison:
        if outcome.chosen:
            return outcome.best
    return None


def _stockouts(revision: PlanRevision, limit: float) -> list[RiskFinding]:
    if revision.simulation is None:
        return []
    return [
        RiskFinding(
            code=RiskCode.STOCKOUT_RISK,
            message=(
                f"{line.sku_id} in {line.region} runs out of stock in "
                f"{format_percent(line.stockout_probability)} of the simulated runs, at or "
                f"above the {format_percent(limit)} limit"
            ),
            feedback=(
                f"Promote {line.sku_id} in {line.region} less deeply, for fewer weeks or for a "
                f"narrower target segment, or leave {line.sku_id} out of generate_candidates' "
                "sku_ids, so its demand stays within its stock."
            ),
            sku_id=line.sku_id,
            region=line.region,
            actual=line.stockout_probability,
            limit=limit,
        )
        for line in revision.simulation.lines
        if line.stockout_probability >= limit - _EPSILON
    ]
