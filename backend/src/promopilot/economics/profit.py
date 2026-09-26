"""Margin, gross profit, incremental profit and clearance value (ADR 0005)."""

from collections.abc import Sequence
from typing import Any, cast

import numpy as np

from promopilot.economics.money import Amount, Money


def margin(price: Money, unit_cost: Amount) -> Money:
    """(price - cost) / price."""
    value: Any = price
    return cast(Money, (value - unit_cost) / value)


def gross_profit(units: Money, price: Amount, unit_cost: Amount) -> Money:
    """units x (price - cost)."""
    value: Any = units
    return cast(Money, value * (price - unit_cost))


def blended_margin(revenues: Sequence[float], gross_profits: Sequence[float]) -> float | None:
    """Revenue-weighted margin of several plan lines; None when there is no revenue."""
    total_revenue = sum(revenues)
    if total_revenue == 0:
        return None
    return sum(gross_profits) / total_revenue


def incremental_profit(
    promoted_gross_profit: Money, baseline_gross_profit: Amount, fixed_marketing_cost: float
) -> Money:
    """Gross profit gained over baseline, net of the fixed marketing cost (ADR 0015).

    Both gross profits must cover the promo weeks and the pull-forward weeks after them, so
    the post-promo dip is netted off. Discount funding is already in the lower price.
    """
    promoted: Any = promoted_gross_profit
    return cast(Money, promoted - baseline_gross_profit - fixed_marketing_cost)


def clearance_value(
    units_sold: Money, baseline_units: Amount, unit_cost: Amount, write_off_rate: float
) -> Money:
    """The write-off loss avoided by selling overstocked units beyond baseline."""
    extra: Any = np.maximum(units_sold - baseline_units, 0)
    value = extra * unit_cost * write_off_rate
    return cast(Money, value if isinstance(value, np.ndarray) else float(value))
