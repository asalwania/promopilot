"""Promo economics (ADR 0005): pure definitions shared by the optimiser, simulator and oracle.

Money is in rupees as floats (ADR 0015). Every function works on scalars and, elementwise,
on numpy arrays, so the vectorised simulator can use the same definitions.
"""

from promopilot.economics.costs import discount_funding, fixed_marketing_cost, promo_cost
from promopilot.economics.pricing import effective_unit_price
from promopilot.economics.profit import (
    blended_margin,
    clearance_value,
    gross_profit,
    incremental_profit,
    margin,
)

__all__ = [
    "blended_margin",
    "clearance_value",
    "discount_funding",
    "effective_unit_price",
    "fixed_marketing_cost",
    "gross_profit",
    "incremental_profit",
    "margin",
    "promo_cost",
]
