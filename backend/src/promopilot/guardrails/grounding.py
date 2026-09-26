"""Numeric grounding: every number in a text must appear in tool outputs (SPEC §9.6, ADR 0028).

A number in the text matches a tool-output number when that number, rounded to the
precision the text shows, equals it: "₹6.2 lakh" covers ₹6,15,000-₹6,25,000 and "18%"
covers 17.5-18.5, matched against 18 or 0.18. Signs are ignored.
"""

import math
import re
from bisect import bisect_left
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from numbers import Real

from pydantic import BaseModel, ConfigDict

_MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
)
_DAY = r"\d{1,2}(?:st|nd|rd|th)?"
_DATE = re.compile(
    "|".join(
        [
            r"\b\d{4}-\d{1,2}-\d{1,2}\b",
            r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",
            rf"\b{_DAY}\s+{_MONTH}\b(?:,?\s+\d{{4}}\b)?",
            rf"\b{_MONTH}\s+{_DAY}\b(?:,?\s+\d{{4}}\b)?",
        ]
    ),
    re.IGNORECASE,
)
_NUMBER = re.compile(
    r"(?:(?P<rupee>₹|\bRs\.?|\bINR)\s*)?"
    r"(?P<digits>\d{1,2}(?:,\d{2})+,\d{3}|\d{1,3}(?:,\d{3})+|\d+)(?:\.(?P<decimals>\d+))?(?!\d)"
    r"(?:\s*(?P<unit>%|per\s?cent\b|lakhs?\b|lacs?\b|crores?\b|cr\b))?",
    re.IGNORECASE,
)
_MULTIPLIERS = {"lakh": 1e5, "lac": 1e5, "crore": 1e7, "cr": 1e7}
_REL_TOLERANCE = 1e-9


class GroundingReport(BaseModel):
    """The numbers in a text that no tool output supports, as written, in text order."""

    model_config = ConfigDict(frozen=True)

    ungrounded: tuple[str, ...]

    @property
    def grounded(self) -> bool:
        return not self.ungrounded


@dataclass(frozen=True)
class _Mention:
    text: str
    written: float
    """The number as written, before any lakh or crore multiplier."""
    value: float
    """Absolute value in plain units (rupees, units, or percentage points for a percent)."""
    half_step: float
    """Half the smallest step the text shows: the rounding tolerance."""
    percent: bool
    exempt: bool


def check_numeric_grounding(text: str, tool_outputs: object) -> GroundingReport:
    """Check every number in `text` against the numbers anywhere in `tool_outputs`.

    `tool_outputs` is any JSON-like value (mappings, sequences, strings, numbers) or pydantic
    models; numbers written inside its strings count too. Exempt from the check: numbers
    inside identifiers or words (SKU-0042, W12, 400g), dates, 4-digit years and bare
    integers 0-10.
    """
    values = sorted(set(_tool_numbers(tool_outputs)))
    return GroundingReport(
        ungrounded=tuple(
            mention.text
            for mention in _mentions(text)
            if not mention.exempt and not _supported(mention, values)
        )
    )


def _supported(mention: _Mention, values: list[float]) -> bool:
    tolerance = mention.half_step * (1 + _REL_TOLERANCE) + _REL_TOLERANCE
    if _any_within(values, mention.value, tolerance):
        return True
    # A percent may be stored as a fraction: 18% is 0.18.
    return mention.percent and _any_within(values, mention.value / 100, tolerance / 100)


def _any_within(values: list[float], centre: float, tolerance: float) -> bool:
    index = bisect_left(values, centre - tolerance)
    return index < len(values) and values[index] <= centre + tolerance


def _mentions(text: str, *, exemptions: bool = True) -> Iterator[_Mention]:
    if exemptions:
        text = _DATE.sub(lambda match: " " * len(match.group()), text)
    for match in _NUMBER.finditer(text):
        digits = match["digits"].replace(",", "")
        decimals = match["decimals"] or ""
        unit = (match["unit"] or "").lower().replace(" ", "")
        multiplier = _MULTIPLIERS.get(unit.rstrip("s"), 1.0)
        percent = unit in {"%", "percent"}
        written = float(f"{digits}.{decimals or 0}")
        yield _Mention(
            text=match.group().strip(),
            written=written,
            value=written * multiplier,
            half_step=0.5 * 10.0 ** -len(decimals) * multiplier,
            percent=percent,
            exempt=exemptions and _is_exempt(text, match),
        )


def _is_exempt(text: str, match: re.Match[str]) -> bool:
    start, end = match.start(), match.end()
    before = text[start - 1] if start >= 1 else ""
    before_that = text[start - 2] if start >= 2 else ""
    after = text[end : end + 1]
    in_word = (
        _is_word_char(before)
        or (before in {"-", "_", "/", "."} and _is_word_char(before_that, letters_only=True))
        or _is_word_char(after)
    )
    if in_word:
        return True
    bare_integer = not (
        match["rupee"] or match["unit"] or match["decimals"] or "," in match.group()
    )
    if not bare_integer:
        return False
    value = int(match["digits"])
    return value <= 10 or (len(match["digits"]) == 4 and 1900 <= value <= 2100)


def _is_word_char(char: str, *, letters_only: bool = False) -> bool:
    if not char:
        return False
    return char.isalpha() or char == "_" or (not letters_only and char.isdigit())


def _tool_numbers(value: object) -> Iterator[float]:
    if isinstance(value, BaseModel):
        yield from _tool_numbers(value.model_dump())
    elif isinstance(value, str):
        for mention in _mentions(value, exemptions=False):
            yield mention.value
            yield mention.written
    elif isinstance(value, bool) or value is None:
        return
    elif isinstance(value, Real):
        number = abs(float(value))
        if math.isfinite(number):
            yield number
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _tool_numbers(item)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from _tool_numbers(item)
