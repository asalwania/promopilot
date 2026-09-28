"""The rupee amounts and percentages a text states, read by strict rules (ADR 0053).

The Context agent's fallback reading uses this when the LLM is down, so every number it puts
in a planning request is one the manager wrote. It lives here, not in `promopilot.agents`,
because turning "₹2 lakh" into 200000 is arithmetic (ADR 0049 D10).

- **Rupees** need a rupee sign (₹, Rs, INR) or a lakh, lac, crore or cr word: "₹8 lakh",
  "2 lakh", "Rs 5,00,000". The shorthands k, L and Cr count only right after a rupee sign
  ("₹90k", "₹2L", "₹1.5Cr"), so "2L cola" and "90k units" are never money.
- **Percentages** are written with %, "percent" or "per cent" and read as fractions.
- A number inside a word or identifier ("400g", "SKU0002", "W108") is never read, and a bare
  number only when the caller says what unit it was asked in (an answer to "what budget, in
  rupees?").
"""

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

_MULTIPLIERS: Final = {
    "k": 1e3,
    "l": 1e5,
    "lakh": 1e5,
    "lac": 1e5,
    "cr": 1e7,
    "crore": 1e7,
}
_NUMBER = re.compile(
    r"(?:(?P<rupee>₹|\bRs\.?|\bINR\b)\s*)?"
    r"(?P<digits>\d{1,2}(?:,\d{2})+,\d{3}|\d{1,3}(?:,\d{3})+|\d+)(?:\.(?P<decimals>\d+))?"
    r"(?:\s*(?P<unit>%|per\s?cent\b|lakhs?\b|lacs?\b|crores?\b|cr\b)|(?P<short>k|l|cr)\b)?",
    re.IGNORECASE,
)


class StatedKind(StrEnum):
    RUPEES = "rupees"
    PERCENT = "percent"


@dataclass(frozen=True)
class StatedNumber:
    """A number as the text states it: rupees, or a percentage as a fraction (18% is 0.18)."""

    kind: StatedKind
    value: float
    text: str
    """As written, e.g. "₹2 lakh"."""
    start: int
    end: int


def read_stated_numbers(text: str, *, bare: StatedKind | None = None) -> tuple[StatedNumber, ...]:
    """Every rupee amount and percentage `text` states, in text order. A bare number counts as
    `bare` when it is given, and is skipped otherwise."""
    found = []
    for match in _NUMBER.finditer(text):
        number = _stated(text, match, bare)
        if number is not None:
            found.append(number)
    return tuple(found)


def _stated(text: str, match: re.Match[str], bare: StatedKind | None) -> StatedNumber | None:
    rupee, unit, short = match["rupee"], (match["unit"] or "").lower(), match["short"]
    digits_at = match.start("digits")
    before = text[digits_at - 1] if digits_at and not rupee else ""
    after = text[match.end() : match.end() + 1]
    if _in_word(before) or _in_word(after) or (short and not rupee):
        return None
    written = float(match["digits"].replace(",", "") + "." + (match["decimals"] or "0"))
    if unit == "%" or unit.startswith("per"):
        kind, value = StatedKind.PERCENT, round(written / 100, 6)
    elif rupee or unit or short:
        multiplier = _MULTIPLIERS.get((unit or short or "").lower().rstrip("s"), 1.0)
        kind, value = StatedKind.RUPEES, round(written * multiplier, 2)
    elif bare is StatedKind.PERCENT:
        kind, value = bare, round(written / 100, 6)
    elif bare is StatedKind.RUPEES:
        kind, value = bare, written
    else:
        return None
    start = match.start("rupee") if rupee else digits_at
    return StatedNumber(kind, value, text[start : match.end()].strip(), start, match.end())


def _in_word(char: str) -> bool:
    return bool(char) and (char.isalnum() or char == "_")
