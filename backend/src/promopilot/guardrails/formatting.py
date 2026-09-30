"""Display formats for explanations (ADR 0050), the inverse of numeric grounding's parser.

Money below ₹1 lakh is shown in whole rupees with Indian digit grouping (₹18,250), then in
lakh (₹1.72 lakh) and crore (₹1.25 crore) to at most two decimals. Percentages show at most
one decimal and units are whole. Each rounds only as far as the text shows, so
`check_numeric_grounding` (ADR 0028) always accepts it for the value it was formatted from.
"""

LAKH = 1e5
CRORE = 1e7


def format_rupees(amount: float) -> str:
    """₹0, ₹18,250, -₹13,813, ₹1 lakh, ₹1.72 lakh, ₹1.25 crore, ₹1,234.57 crore."""
    size = abs(amount)
    if round(size) < LAKH:
        shown = _indian_grouping(round(size))
    elif round(size / LAKH, 2) < CRORE / LAKH:
        shown = f"{_trimmed(f'{size / LAKH:.2f}')} lakh"
    else:
        shown = f"{_trimmed(f'{size / CRORE:,.2f}')} crore"
    return f"{_sign(amount, shown)}₹{shown}"


def format_percent(fraction: float) -> str:
    """A fraction as a percentage with at most one decimal: 0.2237 is 22.4%, 0.25 is 25%."""
    shown = _trimmed(f"{abs(fraction) * 100:.1f}")
    return f"{_sign(fraction, shown)}{shown}%"


def format_percentile(quantile: float) -> str:
    """A quantile as the percentile it names: 0.9 is P90, 0.1 is P10 (ADR 0080)."""
    return f"P{round(quantile * 100)}"


def format_units(units: float) -> str:
    """Whole units with Indian digit grouping: 1,23,456."""
    return _indian_grouping(round(units))


def _indian_grouping(whole: int) -> str:
    digits = str(abs(whole))
    head, tail = digits[:-3], digits[-3:]
    groups: list[str] = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join([*groups, tail])


def _trimmed(number: str) -> str:
    """Drop trailing zeros after the point: a shorter number only widens its rounding."""
    return number.rstrip("0").rstrip(".") if "." in number else number


def _sign(value: float, shown: str) -> str:
    return "-" if value < 0 and shown.strip("0.,") else ""
