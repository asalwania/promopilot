"""Money in rupees: a float, or a float array for vectorised callers (ADR 0015)."""

from typing import TypeVar

import numpy as np
from numpy.typing import NDArray

Money = TypeVar("Money", float, NDArray[np.float64])
"""The shape-carrying argument: the result is a float or an array to match it."""

Amount = float | NDArray[np.float64]
"""Any other money or quantity argument, broadcast against the Money argument."""
