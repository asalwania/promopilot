"""Effective unit price per mechanism."""

from typing import Any, cast

import numpy as np

from promopilot.domain import Mechanism
from promopilot.economics.money import Money


def effective_unit_price(mechanism: Mechanism, base_price: Money, depth_pct: int) -> Money:
    """What the shopper pays per unit under a mechanism at a depth.

    - PCT_OFF: depth % off the base price.
    - BOGO: buy one, get one free, an effective 50% off per unit.
    - FIXED_PRICE: the largest whole-rupee charm price ending in 9 at or below the
      depth price (₹110 at 10% → ₹99).
    - BUNDLE: depth % off the pair's price, split between the two SKUs pro-rata by base
      price, which leaves each SKU at depth % off its own base price.
    """
    price: Any = base_price
    if mechanism is Mechanism.BOGO:
        return cast(Money, price * 0.5)
    depth_price = np.round(price * (1 - depth_pct / 100), 2)
    if mechanism is not Mechanism.FIXED_PRICE:
        return cast(Money, _like(price, depth_price))
    if np.any(depth_price < 9):
        raise ValueError(f"no charm price ending in 9 at or below ₹{np.min(depth_price):.2f}")
    return cast(Money, _like(price, np.floor((depth_price - 9) / 10) * 10 + 9))


def _like(template: Any, value: Any) -> Any:
    """Return a plain float for scalar inputs and an array for array inputs."""
    return value if isinstance(template, np.ndarray) else float(value)
