"""How the optimiser chose a plan: solver status, binding constraints, why each plan line was
chosen and why the best rejected options were not (SPEC §9.4, F-01, ADR 0038)."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from promopilot.domain.plan import PlanLine
from promopilot.domain.vocabulary import Region


class SolveStatus(StrEnum):
    OPTIMAL = "OPTIMAL"
    """The plan is proven best."""
    FEASIBLE = "FEASIBLE"
    """The time limit ran out first: the best plan found, not proven best."""
    INFEASIBLE = "INFEASIBLE"


class ConstraintKind(StrEnum):
    """A plan-level constraint the optimiser enforces (ADR 0036, ADR 0038)."""

    MARKETING_BUDGET = "marketing_budget"
    MINIMUM_MARGIN = "minimum_margin"
    """The brief's minimum margin, where it is above the company-policy margin floor."""
    MARGIN_FLOOR = "margin_floor"
    """The company-policy margin floor, where the brief sets no higher minimum margin."""
    MAX_PROMOTED_SKUS = "max_promoted_skus"
    """The maximum number of promoted SKUs in one category and region: company policy's, or
    the brief's where it is tighter."""
    REGIONAL_BUDGET = "regional_budget"
    """The brief's cap on the promo cost spent in one region."""
    CLEARANCE_TARGET = "clearance_target"
    """The sell-through the brief asks for a SKU it names for clearance, in one region."""
    KVI_PRICE_TOLERANCE = "kvi_price_tolerance"
    """No KVI promo price more than the tolerance above the competitor price (ADR 0031)."""


class ConstraintSource(StrEnum):
    """Who set a constraint: only the brief's constraints may be relaxed (ADR 0007)."""

    BRIEF = "brief"
    COMPANY_POLICY = "company_policy"


class BindingEvidence(StrEnum):
    """How sure the optimiser is that a constraint binds (ADR 0038)."""

    EXACT = "exact"
    """Re-solved to optimality without it: the objective gains exactly `objective_gain`."""
    LOWER_BOUND = "lower_bound"
    """The re-solve without it timed out after finding a better plan: it binds, and the
    objective gains at least `objective_gain`."""
    UNPROVEN = "unproven"
    """It may bind, but the time for re-solving ran out before that was settled."""


class BindingConstraint(BaseModel):
    """A constraint that limits the plan: dropping it gives a strictly better objective, or,
    when time ran out, one that may."""

    model_config = ConfigDict(frozen=True)

    kind: ConstraintKind
    source: ConstraintSource
    limit: float
    """Rupees for a budget, a fraction for a margin, a sell-through or the KVI price
    tolerance, a SKU count for the promoted-SKU cap."""
    category: str | None = None
    """The category, for the promoted-SKU cap."""
    region: Region | None = None
    """The region, for the promoted-SKU cap, a regional budget cap or a clearance target."""
    sku_id: str | None = None
    """The SKU, for a clearance target."""
    evidence: BindingEvidence
    objective_gain: float | None
    """Rupees the objective gains when the constraint is dropped: exact, or at least this
    much; None when unproven."""


class SelectionReasonCode(StrEnum):
    """A positive part of a plan line's value (ADR 0005, ADR 0035)."""

    INCREMENTAL_PROFIT = "incremental_profit"
    CLEARANCE_VALUE = "clearance_value"
    HALO = "halo"


class SelectionReason(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: SelectionReasonCode
    amount: float
    """Rupees, always positive."""


class WhyChosen(BaseModel):
    """Why a plan line was chosen: the positive parts of its value, what it is worth alone,
    and whether it is the best option the optimiser could pick for its SKU and region."""

    model_config = ConfigDict(frozen=True)

    reasons: tuple[SelectionReason, ...]
    value: float
    """incremental profit - cannibalisation + halo + clearance value (rupees)."""
    best_for_sku_region: bool


class NotSelectedReason(StrEnum):
    """Why a promo option is not in the plan: a rule it breaks alone or added to the plan."""

    LOW_UPLIFT = "low_uplift"
    """It is not worth a paisa on its own."""
    OUT_OF_STOCK = "out_of_stock"
    """Its P90 units, or a BUNDLE partner's, exceed available stock."""
    BREAKS_POLICY = "breaks_policy"
    """Outside the promo window, deeper than the maximum discount, or below unit cost."""
    OVER_BUDGET = "over_budget"
    OVER_REGIONAL_BUDGET = "over_regional_budget"
    BREAKS_MARGIN = "breaks_margin"
    MAX_PROMOTED_SKUS = "max_promoted_skus"
    MISSES_CLEARANCE_TARGET = "misses_clearance_target"
    """Adding it would leave a clearance target the plan meets unmet."""
    BREAKS_KVI_TOLERANCE = "breaks_kvi_tolerance"
    """A KVI it promotes would stay priced above the competitor beyond the tolerance."""
    CANNIBALISES = "cannibalises"
    """What it loses together with plan lines outweighs its value."""
    TIME_LIMIT = "time_limit"
    """The solver ran out of time before it could rule the option in or out."""


class NotSelectedOption(BaseModel):
    """The best option of a SKU and region with no plan line, and why it was left out."""

    model_config = ConfigDict(frozen=True)

    option: PlanLine
    value: float
    """What the option is worth alone (rupees)."""
    reasons: tuple[NotSelectedReason, ...]
    cannibalises: tuple[str, ...] = ()
    """The plan lines' SKUs it loses too much with, for CANNIBALISES."""


class PruneReason(StrEnum):
    """Why option generation dropped an enumerated promo option, in the order the rules are
    applied (ADR 0035)."""

    NO_CHARM_PRICE = "no_charm_price"
    """A FIXED_PRICE depth whose price is below ₹9: there is no charm price to sell at."""
    MAX_DISCOUNT = "max_discount"
    BELOW_COST = "below_cost"
    DUPLICATE_PRICE = "duplicate_price"
    STOCK = "stock"
    PARTNER_STOCK = "partner_stock"


class ClearanceShortfall(BaseModel):
    """A clearance target the plan misses: no plan within the other constraints reaches it,
    so the optimiser returned the plan that comes closest and reports by how much it falls
    short (SPEC §9.4, F-06 AC2, ADR 0040)."""

    model_config = ConfigDict(frozen=True)

    sku_id: str
    region: Region
    target: float
    """The sell-through the brief asked for."""
    expected_sell_through: float
    """What the plan is expected to reach: units sold over the promo window / available
    stock."""
    shortfall_units: float
    """Units short of the target."""
