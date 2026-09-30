"""The safety margin's arithmetic (ADR 0080): how a plan line's promo cost, units and margin
count against the budget, its stock and the minimum margin.

Each is linear in the plan's lines, so the optimiser keeps them as ordinary constraint rows
and `validate_plan` checks the same numbers:

- promo cost at the budget quantile: cost + z x its std, where the std scales each SKU's
  discount funding by the coefficient of variation of its units;
- units at the stock buffer: expected units + k x their std;
- the minimum margin with each line's units moved z x their std towards whichever side lowers
  the blend below it: m x revenue - gross profit, scaled by 1 + z x cv where the line is
  below the minimum and by max(1 - z x cv, 0) where it is above. The blended margin reaches
  the minimum at every such move exactly when the scaled shortfalls sum to at most zero.

The std is the demand model's own (parameter uncertainty and demand noise, ADR 0024).
"""

from statistics import NormalDist

import numpy as np

from promopilot.domain import SafetyMargin

_STANDARD = NormalDist()
_MARGIN_ITERATIONS = 100


def budget_z(margin: SafetyMargin) -> float:
    """Standard deviations of promo cost the budget quantile adds; 0 at the median."""
    return _STANDARD.inv_cdf(margin.budget_quantile) if margin.budget_quantile > 0.5 else 0.0


def margin_z(margin: SafetyMargin) -> float:
    """Standard deviations of units the margin quantile moves each line by; 0 at the median."""
    return -_STANDARD.inv_cdf(margin.margin_quantile) if margin.margin_quantile < 0.5 else 0.0


def _cv(units: np.ndarray, units_std: np.ndarray) -> np.ndarray:
    units, units_std = np.asarray(units, float), np.asarray(units_std, float)
    return np.asarray(np.divide(units_std, units, out=np.zeros_like(units), where=units > 0))


def units_cv(units: np.ndarray, units_std: np.ndarray) -> np.ndarray:
    """Each line's units std over its expected units; 0 where it sells none."""
    return _cv(units, units_std)


def promo_cost_std(
    *,
    anchor_funding: np.ndarray,
    units: np.ndarray,
    units_std: np.ndarray,
    partner_funding: np.ndarray,
    partner_units: np.ndarray,
    partner_units_std: np.ndarray,
) -> np.ndarray:
    """The std of each line's promo cost: its discount funding moves with its units, the
    fixed marketing cost does not. A BUNDLE's partner adds its own share."""
    anchor = np.asarray(anchor_funding, float) * _cv(units, units_std)
    partner = np.asarray(partner_funding, float) * _cv(partner_units, partner_units_std)
    return np.asarray(anchor + partner)


def planned_promo_cost(cost: np.ndarray, cost_std: np.ndarray, margin: SafetyMargin) -> np.ndarray:
    """Each line's promo cost at the budget quantile."""
    return np.asarray(cost, float) + budget_z(margin) * np.asarray(cost_std, float)


def stock_units(units: np.ndarray, units_std: np.ndarray, margin: SafetyMargin) -> np.ndarray:
    """The units each line must fit into its available stock: expected units plus the stock
    buffer's standard deviations."""
    return np.asarray(units, float) + margin.stock_sigmas * np.asarray(units_std, float)


def margin_shortfall(
    revenue: np.ndarray,
    gross_profit: np.ndarray,
    units_cv: np.ndarray,
    *,
    minimum: float,
    margin: SafetyMargin,
) -> np.ndarray:
    """Each line's minimum x revenue - gross profit with its units at the margin quantile,
    on the side that lowers the blend: the plan keeps the minimum when they sum to <= 0."""
    short = minimum * np.asarray(revenue, float) - np.asarray(gross_profit, float)
    move = margin_z(margin) * np.asarray(units_cv, float)
    return np.asarray(np.where(short > 0, short * (1 + move), short * np.maximum(1 - move, 0.0)))


def planned_margin(
    revenue: np.ndarray, gross_profit: np.ndarray, units_cv: np.ndarray, margin: SafetyMargin
) -> float | None:
    """The least blended margin with each line's units anywhere within the margin quantile:
    the highest minimum the plan keeps. None when the plan has no revenue.

    Dinkelbach's iteration on the ratio: each step moves every line to the side that lowers
    the blend at the current margin, and the margin falls until no move lowers it."""
    revenue, gross_profit = np.asarray(revenue, float), np.asarray(gross_profit, float)
    if revenue.sum() <= 0:
        return None
    move = margin_z(margin) * np.asarray(units_cv, float)
    level = float(gross_profit.sum() / revenue.sum())
    for _ in range(_MARGIN_ITERATIONS):
        scale = np.where(level * revenue - gross_profit > 0, 1 + move, np.maximum(1 - move, 0.0))
        sold = float((revenue * scale).sum())
        if sold <= 0:
            return None
        lower = float((gross_profit * scale).sum() / sold)
        if lower >= level - 1e-15:
            break
        level = lower
    return level
