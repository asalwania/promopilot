"""The mechanism comparator (SPEC F-02, ADR 0041): each mechanism's best promo option for a
SKU in a region, compared on the same footing."""

from promopilot.mechanisms.compare import ComparisonContext, compare

__all__ = ["ComparisonContext", "compare"]
