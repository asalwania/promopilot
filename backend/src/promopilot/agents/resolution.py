"""Brief-to-catalogue resolution: the entities a brief's phrases name, with match scores.

The Context agent's LLM lifts phrases out of a brief ("400g namkeen packs", "North and West",
"Diwali"); this module maps each to catalogue entities with no LLM, so the same phrase and
data always give the same answer (ADR 0032). Every candidate carries a match score in [0, 1]
that the Context agent can use as an assumption's confidence, and a resolution is
`ambiguous` when the agent should ask instead of assume (AG-01, AG-02).

Scoring. A phrase is cut into meaningful words: lower case, plurals and filler words ("packs",
"products", "and") dropped, "400 g" joined to "400g". A candidate is a set of catalogue terms
(a category, region, brand, pack size, holiday, ...). Its score is the mean, over every
phrase word and every word of its terms, of that word's best difflib similarity on the other
side; similarities below `MATCH_FLOOR` count as 0, and words with digits match only exactly.
So a score is 1.0 exactly when every phrase word names a term and every term word is named.

Only the calendar is read past the as-of week (holidays are known in advance), and a promo
window only uses weeks after it (ADR 0008).
"""

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from statistics import fmean
from typing import Protocol, Self

import pandas as pd

from promopilot.domain import PromoWindow, Region

AMBIGUOUS_BELOW = 0.7
"""A best score below this is too unsure to assume (the AG-02 confidence threshold)."""
RUNNER_UP_MARGIN = 0.1
"""A runner-up scoring within this of the best makes a resolution ambiguous."""
MATCH_FLOOR = 0.6
"""Word similarities below this count as no match."""
MAX_CANDIDATES = 5

_PRODUCT_KINDS = {
    "category": "category",
    "subcategory": "subcategory",
    "brand": "brand",
    "pack_size": "pack size",
}
_FILLERS = frozenset(
    {
        *("a", "all", "an", "and", "any", "around", "across", "at", "categories", "category"),
        *("during", "every", "festival", "for", "from", "holiday", "in", "india", "item"),
        *("of", "on", "or", "our", "pack", "plan", "product", "promo", "promotion", "range"),
        *("region", "sale", "season", "sku", "some", "store", "the", "this", "to", "week"),
        *("window", "with", "zone"),
    }
)
_QUANTITY = re.compile(
    r"(\d+(?:\.\d+)?)\s*(kgs?|kilograms?|gms?|grams?|g|ml|millilit(?:re|er)s?|ltrs?|lit(?:re|er)s?|l)\b"
)
_WORD = re.compile(r"[a-z0-9]+(?:[.x][a-z0-9]+)*")


class ResolverData(Protocol):
    """The reads the resolver makes (`promopilot.data.RetailData`)."""

    async def products(self) -> pd.DataFrame: ...
    async def calendar(self) -> pd.DataFrame: ...


@dataclass(frozen=True)
class Candidate[T]:
    """One reading of a phrase: what it resolves to, a human label and its match score."""

    value: T
    label: str
    score: float


@dataclass(frozen=True)
class Resolution[T]:
    """A phrase's candidates, best first."""

    phrase: str
    candidates: tuple[Candidate[T], ...]

    @property
    def best(self) -> Candidate[T] | None:
        return self.candidates[0] if self.candidates else None

    @property
    def ambiguous(self) -> bool:
        """No candidate, a best below `AMBIGUOUS_BELOW`, or a runner-up close behind it."""
        if not self.candidates or self.candidates[0].score < AMBIGUOUS_BELOW:
            return True
        return len(self.candidates) > 1 and (
            self.candidates[0].score - self.candidates[1].score <= RUNNER_UP_MARGIN + 1e-9
        )


@dataclass(frozen=True)
class _Term:
    kind: str
    value: str
    words: tuple[str, ...]


class BriefResolver:
    """Resolves brief phrases against the catalogue, regions and calendar at an as-of week."""

    def __init__(self, products: pd.DataFrame, calendar: pd.DataFrame, as_of_week: int) -> None:
        self._products = products.sort_values("sku_id").reset_index(drop=True)
        self._calendar = calendar
        self._as_of_week = as_of_week
        self._categories = list(dict.fromkeys(self._products["category"]))
        known = set(calendar["region"])
        self._regions = [region for region in Region if region.value in known]
        self._product_terms = [
            term
            for kind in _PRODUCT_KINDS
            for term in _terms(kind, dict.fromkeys(self._products[kind]))
        ]

    @classmethod
    async def load(cls, data: ResolverData, *, as_of_week: int) -> Self:
        return cls(await data.products(), await data.calendar(), as_of_week)

    def categories(self, phrase: str) -> Resolution[tuple[str, ...]]:
        """Categories, in catalogue order: "Snacks and Beverages" → (Snacks, Beverages)."""
        order = {name: n for n, name in enumerate(self._categories)}

        def value(terms: tuple[_Term, ...]) -> tuple[tuple[str, ...], str] | None:
            names = tuple(sorted({t.value for t in terms}, key=order.__getitem__))
            return names, ", ".join(names)

        return _resolve(phrase, _terms("category", self._categories), value)

    def regions(self, phrase: str) -> Resolution[tuple[Region, ...]]:
        """Regions, in the order North, South, East, West: "North and West" → (North, West)."""

        def value(terms: tuple[_Term, ...]) -> tuple[tuple[Region, ...], str] | None:
            named = {t.value for t in terms}
            regions = tuple(region for region in self._regions if region.value in named)
            return regions, ", ".join(region.value for region in regions)

        return _resolve(phrase, _terms("region", [r.value for r in self._regions]), value)

    def products(
        self, phrase: str, *, categories: Sequence[str] | None = None
    ) -> Resolution[tuple[str, ...]]:
        """SKU ids, sorted: "400g namkeen packs" → every SKU that is Namkeen and 400g.

        Terms of one kind are alternatives ("namkeen and chips"); terms of different kinds
        must all hold. `categories` limits the SKUs to those categories.
        """
        products = self._products
        if categories is not None:
            products = products[products["category"].isin(categories)]

        def value(terms: tuple[_Term, ...]) -> tuple[tuple[str, ...], str] | None:
            chosen = products
            parts = []
            for kind, name in _PRODUCT_KINDS.items():
                values = sorted({t.value for t in terms if t.kind == kind})
                if values:
                    chosen = chosen[chosen[kind].isin(values)]
                    parts.append(f"{name} {' or '.join(values)}")
            if chosen.empty:
                return None
            return tuple(chosen["sku_id"]), "; ".join(parts)

        return _resolve(phrase, self._product_terms, value)

    def promo_window(self, phrase: str, *, regions: Sequence[Region]) -> Resolution[PromoWindow]:
        """The weeks after the as-of week that the calendar labels with the named holiday.

        "Diwali" → its first run of labelled weeks (lead-in and festival week) in any of the
        regions. A holiday that does not fall in these regions after the as-of week is no
        candidate.
        """
        calendar = self._calendar
        ahead = calendar[
            (calendar["week_id"] > self._as_of_week)
            & calendar["region"].isin([r.value for r in regions])
        ].dropna(subset=["holiday_name"])
        weeks = {
            str(name): sorted({int(w) for w in rows["week_id"]})
            for name, rows in ahead.groupby("holiday_name", sort=True)
        }

        def value(terms: tuple[_Term, ...]) -> tuple[PromoWindow, str] | None:
            runs = sorted((*_first_run(weeks[t.value]), t.value) for t in terms)
            start, end = runs[0][0], max(run[1] for run in runs)
            names = " + ".join(run[2] for run in runs)
            return PromoWindow(start_week=start, end_week=end), f"{names} (weeks {start}-{end})"

        return _resolve(phrase, _terms("holiday", weeks), value)


def _resolve[T](
    phrase: str,
    terms: Sequence[_Term],
    value_of: Callable[[tuple[_Term, ...]], tuple[T, str] | None],
) -> Resolution[T]:
    words = _words(phrase)
    options = [_options(word, terms, words) for word in words]
    matched = [n for n, found in enumerate(options) if found]
    if not matched:
        return Resolution(phrase, ())
    primary = {n: options[n][0][1] for n in matched}
    choices = [primary]
    for n in matched:
        top = options[n][0][0]
        for similarity, term in options[n][1:]:
            # An exact word match is only contested by another exact match.
            if top < 1.0 or similarity == 1.0:
                choices.append(primary | {n: term})
    candidates: dict[str, Candidate[T]] = {}
    for choice in choices:
        chosen = tuple(dict.fromkeys(choice[n] for n in matched))
        resolved = value_of(chosen)
        if resolved is None:
            continue
        value, label = resolved
        candidate = Candidate(value, label, _score(words, chosen))
        key = repr(value)
        if key not in candidates or candidates[key].score < candidate.score:
            candidates[key] = candidate
    ranked = sorted(candidates.values(), key=lambda c: (-c.score, c.label))
    return Resolution(phrase, tuple(ranked[:MAX_CANDIDATES]))


def _options(word: str, terms: Sequence[_Term], words: Sequence[str]) -> list[tuple[float, _Term]]:
    """The terms a word may name, best first: ties go to the term the phrase names most."""
    found = []
    for order, term in enumerate(terms):
        similarity = max(_similarity(word, w) for w in term.words)
        if similarity > 0:
            support = sum(max(_similarity(p, w) for w in term.words) for p in words)
            found.append((-similarity, -support, len(term.words), order, term))
    return [(-key[0], key[-1]) for key in sorted(found, key=lambda key: key[:4])]


def _score(words: Sequence[str], terms: Iterable[_Term]) -> float:
    term_words = [w for term in terms for w in term.words]
    named = [max(_similarity(p, w) for w in term_words) for p in words]
    covered = [max(_similarity(p, w) for p in words) for w in term_words]
    return round(fmean(named + covered), 3)


def _similarity(a: str, b: str) -> float:
    if a == b:
        return 1.0
    if any(ch.isdigit() for ch in a + b):
        return 0.0
    ratio = SequenceMatcher(None, a, b).ratio()
    return ratio if ratio >= MATCH_FLOOR else 0.0


def _terms(kind: str, values: Iterable[str]) -> list[_Term]:
    return [_Term(kind, str(value), words) for value in values if (words := _words(str(value)))]


def _words(text: str) -> tuple[str, ...]:
    text = _QUANTITY.sub(lambda m: m.group(1) + _unit(m.group(2)), text.lower())
    words = []
    for raw in _WORD.findall(text):
        word = _singular(raw)
        if raw not in _FILLERS and word not in _FILLERS:
            words.append(word)
    return tuple(words)


def _unit(unit: str) -> str:
    if unit.startswith("k"):
        return "kg"
    if unit.startswith("g"):
        return "g"
    if unit.startswith("m"):
        return "ml"
    return "l"


def _singular(word: str) -> str:
    plural = len(word) > 3 and word.endswith("s") and not word.endswith("ss")
    return word[:-1] if plural and not any(ch.isdigit() for ch in word) else word


def _first_run(weeks: Sequence[int]) -> tuple[int, int]:
    start = end = weeks[0]
    while end + 1 in weeks:
        end += 1
    return start, end
