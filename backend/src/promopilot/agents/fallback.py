"""The Context agent's fallback reading: the brief read by deterministic rules when the LLM is
unavailable, so planning still runs end to end with no LLM (SF-03, #124, ADR 0053).

The rules build the same `BriefReading` the LLM would lift, and `interpret` resolves and checks
it exactly as it does the LLM's (ADR 0048), so the request, assumptions and questions follow
the same rules. The rules only ever read what is written:

- **Scope and holidays** are the catalogue terms and holiday names the text names exactly
  (`BriefResolver.mentions`); "all regions" or "pan-India" name every region.
- **The promo window** is the week ids the text states ("weeks 108-109"), or the calendar's
  weeks of the one holiday it names. Several holidays are asked about.
- **Rupees and percentages** are read by `guardrails.read_stated_numbers` and placed by the
  words around them, clause by clause: an amount in a clause about the budget is the marketing
  budget, one written against a single region ("₹90k for North") is that region's cap, and a
  lone amount is the budget. Several candidates are asked about. A percentage belongs to the
  nearest cue in its clause: margin, clearance (clear, sell-through, overstock) or KVI
  tolerance (competitor, KVI); one with no cue is not read.
- **Answers** are read against the question they answer and override the brief. An answer the
  rules cannot read is asked again.
- **Amendments** are read oldest first: what one states replaces what came before, and "drop"
  or "add" edit the regions and categories. An amendment the rules read nothing from is asked
  about, and its answer is read in its place.

Every value read from the text is an assumption at `FALLBACK_CONFIDENCE`: low next to an LLM
reading's 1.0, yet at the AG-02 threshold, so a brief the rules read fully still plans. Every
assumption of a fallback reading is marked `fallback`.
"""

import copy
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final, Literal

from promopilot.agents.assumptions import ContextReading, ContextWorld, interpret
from promopilot.agents.context import BriefReading, ClearanceAsk, RegionalCap
from promopilot.agents.resolution import BriefResolver, Resolution
from promopilot.agents.state import DegradedReason
from promopilot.domain import (
    Assumption,
    AssumptionSource,
    Clarification,
    ClarificationQuestion,
    QuestionReason,
    Region,
)
from promopilot.guardrails import StatedKind, StatedNumber, read_stated_numbers

FALLBACK_CONFIDENCE: Final = 0.7
"""The confidence of every value the rules read from the text (ADR 0053 D6)."""
AMENDMENT: Final = "amendment"
"""The field of a question about an amendment the rules could not read."""
READ_BY_RULES: Final = "Read by rules: the language model was unavailable."

_SENTENCE_END = re.compile(r"(?<!\bRs)[.!?;](?=\s|$)|\n+", re.IGNORECASE)
_CLAUSE_BREAK = re.compile(
    r",\s|;|:\s|\s[\u2014\u2013-]\s|[\u2014\u2013]|\s(?:and|but|while|whereas|with|plus)\s",
    re.IGNORECASE,
)
_BUDGET = re.compile(r"\b(?:budget\w*|spend\w*|marketing)\b", re.IGNORECASE)
_CAP_LINK = re.compile(
    r"^(?:\s|for|in|on|to|the|region|at|of|is|cap|capped|limit|limited|max|maximum|up|"
    r"most|:|-)*$",
    re.IGNORECASE,
)
_MARGIN = re.compile(r"\bmargins?\b", re.IGNORECASE)
_CLEARANCE = re.compile(
    r"\b(?:clear(?:ance|ing|s)?|sell[- ]?through|overstock\w*|liquidat\w*|excess stock|sell off)\b",
    re.IGNORECASE,
)
_KVI = re.compile(
    r"\b(?:tolerance|competitors?|kvis?|key value items?|price gap|price match\w*)\b",
    re.IGNORECASE,
)
_WEEKS = re.compile(
    r"\b(?:weeks?\s*|wk?\s?)(\d{1,4})(?:\s*(?:-|\u2013|to|through|until)\s*(?:weeks?\s*|wk?\s?)?"
    r"(\d{1,4}))?\b",
    re.IGNORECASE,
)
_SKU_ID = re.compile(r"\bSKU\d{3,}\b", re.IGNORECASE)
_SKU_CAP = re.compile(
    r"\b(?:at most|no more than|up to|max(?:imum)?(?: of)?)\s+(\d{1,3})\s+"
    r"(?:skus?|products?|items?)\s+(?:per|in each|for each|a|in any)\s+category",
    re.IGNORECASE,
)
_OBJECTIVE = re.compile(
    r"\b(?:maximi[sz]e|grow|boost|drive|increase|push|max out)\s+(?:our\s+|the\s+|total\s+)*"
    r"(revenue|turnover|sales volume|unit sales|volume|units|sales)\b",
    re.IGNORECASE,
)
_SEGMENT = re.compile(r"\b(?:target(?:ing)?|aim(?:ed|ing)? at)\s+([a-z][^.;,!?]*)", re.IGNORECASE)
_DROP = re.compile(
    r"\b(?:drop|remove|exclude|excluding|without|except|leave out|skip)\b", re.IGNORECASE
)
_ADD = re.compile(r"\b(?:add|include|including|also|extend(?: it)? to)\b", re.IGNORECASE)

type _Objective = Literal["profit", "revenue", "volume"]
type _Doubt = tuple[str, QuestionReason, tuple[str, ...] | None]
"""A question reworded: its new text, reason and, when replaced, suggestions."""


@dataclass
class _Draft:
    """What the rules have read so far; later text replaces earlier."""

    regions: tuple[Region, ...] | None = None
    categories: tuple[str, ...] | None = None
    sku_ids: tuple[str, ...] = ()
    weeks: tuple[int, int] | None = None
    holiday: str | None = None
    budget: float | None = None
    min_margin: float | None = None
    clearance: list[ClearanceAsk] = field(default_factory=list)
    caps: dict[Region, float] = field(default_factory=dict)
    kvi_tolerance: float | None = None
    sku_cap: int | None = None
    objective: _Objective | None = None
    segment: str | None = None
    doubts: dict[str, _Doubt] = field(default_factory=dict, compare=False)
    """Questions to reword, by question id; used only if `interpret` asks them."""


def read_by_rules(
    brief: str,
    world: ContextWorld,
    *,
    clarifications: Sequence[Clarification] = (),
    amendments: Sequence[str] = (),
    degraded: DegradedReason = DegradedReason.LLM_UNAVAILABLE,
) -> ContextReading:
    """Read the brief, the answers so far and any amendments with no LLM: a planning request
    with its assumptions, or the questions to ask first. Raises `BriefError` only when the
    values read cannot form a planning request at all."""
    return _Rules(world).read(brief, clarifications, amendments, degraded)


class _Rules:
    def __init__(self, world: ContextWorld) -> None:
        self._world = world
        self._resolver = BriefResolver(world.products, world.calendar, world.as_of_week)
        known = set(world.calendar["region"])
        self._regions = tuple(region for region in Region if region.value in known)
        self._categories = tuple(dict.fromkeys(world.products.sort_values("sku_id")["category"]))
        self._skus = set(world.products["sku_id"])
        names = "|".join(re.escape(r.value) for r in self._regions)
        self._region_word = re.compile(rf"\b({names})(?:ern)?\b", re.IGNORECASE)

    def read(
        self,
        brief: str,
        clarifications: Sequence[Clarification],
        amendments: Sequence[str],
        degraded: DegradedReason,
    ) -> ContextReading:
        draft = _Draft()
        self._read_text(brief, draft, amending=False)
        replies: dict[str, str] = {}
        for answer in clarifications:
            if answer.question.field == AMENDMENT:
                replies[answer.question.id] = answer.answer
            else:
                self._read_answer(answer, draft)
        unread = []
        for n, amendment in enumerate(amendments):
            question_id = f"{AMENDMENT}.{n}"
            reply = replies.get(question_id)
            if not self._read_text(reply or amendment, draft, amending=True):
                unread.append(_amendment_question(question_id, amendment, reply))
        result = interpret(self._reading(draft), self._world)
        questions = (*(_reworded(q, draft.doubts) for q in result.questions), *unread)
        return ContextReading(
            request=None if questions else result.request,
            assumptions=tuple(_marked(a) for a in result.assumptions),
            questions=tuple(questions),
            degraded=degraded,
        )

    # --- text: the brief and each amendment ---------------------------------------------------

    def _read_text(self, text: str, draft: _Draft, *, amending: bool) -> bool:
        """Read `text` into the draft; True when it stated anything."""
        before = copy.deepcopy(draft)
        clauses = [clause for sentence in _sentences(text) for clause in _clauses(sentence)]
        self._scope(text, clauses, draft, amending=amending)
        found = tuple(sorted({sku.upper() for sku in _SKU_ID.findall(text)} & self._skus))
        if found:
            draft.sku_ids = found
        self._window(text, draft)
        self._money(clauses, draft)
        self._percentages(text, draft)
        if (cap := _SKU_CAP.search(text)) is not None:
            draft.sku_cap = int(cap.group(1))
        if (objective := _OBJECTIVE.search(text)) is not None:
            draft.objective = _objective(objective.group(1))
        if (segment := _segment(text)) is not None:
            draft.segment = segment
        return draft != before

    def _scope(self, text: str, clauses: Sequence[str], draft: _Draft, *, amending: bool) -> None:
        if not amending:
            mentions = self._resolver.mentions(text)
            draft.regions = mentions.regions or draft.regions
            draft.categories = mentions.categories or draft.categories
            return
        # An amendment: "drop West" and "add Dairy" edit the scope; naming one replaces it.
        named_regions: list[Region] = []
        named_categories: list[str] = []
        for clause in clauses:
            mentions = self._resolver.mentions(clause)
            if _DROP.search(clause):
                draft.regions = _without(draft.regions, mentions.regions)
                draft.categories = _without(draft.categories, mentions.categories)
            elif _ADD.search(clause):
                draft.regions = _in_order(self._regions, draft.regions, mentions.regions)
                draft.categories = _in_order(
                    self._categories, draft.categories, mentions.categories
                )
            else:
                named_regions.extend(mentions.regions)
                named_categories.extend(mentions.categories)
        if named_regions:
            draft.regions = _in_order(self._regions, named_regions)
        if named_categories:
            draft.categories = _in_order(self._categories, named_categories)

    def _window(self, text: str, draft: _Draft) -> None:
        holidays = self._resolver.mentions(text).holidays
        weeks = _WEEKS.search(text)
        if weeks is not None:
            start = int(weeks.group(1))
            end = int(weeks.group(2)) if weeks.group(2) else start
            draft.weeks = (start, end)
            draft.holiday = holidays[0] if len(holidays) == 1 else None
        elif len(holidays) == 1:
            draft.weeks, draft.holiday = None, holidays[0]
        elif holidays:
            draft.weeks, draft.holiday = None, None
            draft.doubts["promo_window"] = (
                f"The brief names several holidays ({', '.join(holidays)}). Which weeks should "
                "the promotion run?",
                QuestionReason.AMBIGUOUS,
                None,
            )

    def _money(self, clauses: Sequence[str], draft: _Draft) -> None:
        cued, loose = [], []
        for clause in clauses:
            for number in read_stated_numbers(clause):
                if number.kind is not StatedKind.RUPEES:
                    continue
                region = self._linked_region(clause, number)
                if _BUDGET.search(clause):
                    cued.append(number)
                elif region is not None:
                    draft.caps[region] = number.value
                else:
                    loose.append(number)
        candidates = cued or loose
        if len(candidates) == 1:
            draft.budget = candidates[0].value
        elif candidates:
            draft.budget = None
            draft.doubts["marketing_budget"] = (
                f"The brief states several amounts ({', '.join(n.text for n in candidates)}). "
                "Which is the marketing budget the plan's promo cost should stay within?",
                QuestionReason.AMBIGUOUS,
                tuple(n.text for n in candidates),
            )

    def _linked_region(self, clause: str, number: StatedNumber) -> Region | None:
        """The one region the amount is written against: "₹90k for North", "North at ₹90k"."""
        linked = set()
        for match in self._region_word.finditer(clause):
            between = (
                clause[number.end : match.start()]
                if match.start() >= number.end
                else clause[match.end() : number.start]
            )
            if _CAP_LINK.match(between):
                linked.add(match.group(1).capitalize())
        if len(linked) != 1:
            return None
        [name] = linked
        return Region(name)

    def _percentages(self, text: str, draft: _Draft) -> None:
        previous = ""
        for sentence in _sentences(text):
            clearing: list[float | None] = []
            for clause in _clauses(sentence):
                for number in read_stated_numbers(clause):
                    if number.kind is not StatedKind.PERCENT:
                        continue
                    cue = _cue(clause, number)
                    if cue == "margin":
                        draft.min_margin = number.value
                    elif cue == "kvi":
                        draft.kvi_tolerance = number.value
                    elif cue == "clearance":
                        clearing.append(number.value)
            if clearing or _CLEARANCE.search(sentence):
                phrase = self._products(sentence) or self._products(previous) or sentence.strip()
                for sell_through in clearing or [None]:
                    _add_clearance(draft, ClearanceAsk(products=phrase, sell_through=sell_through))
            previous = sentence

    def _products(self, text: str) -> str:
        """The product names a text mentions, with its money and percentages blanked out
        ("₹2L" is no 2L pack)."""
        for number in read_stated_numbers(text, bare=StatedKind.PERCENT):
            text = text.replace(number.text, " ")
        return " ".join(self._resolver.mentions(text).products)

    # --- answers ------------------------------------------------------------------------------

    def _read_answer(self, answer: Clarification, draft: _Draft) -> None:
        question = answer.question
        if self._answer(question, answer.answer, draft):
            draft.doubts.pop(question.id, None)
            return
        draft.doubts[question.id] = (
            f'"{answer.answer}" could not be read while the language model is unavailable. '
            f"{question.question}",
            QuestionReason.LOW_CONFIDENCE,
            None,
        )

    def _answer(self, question: ClarificationQuestion, text: str, draft: _Draft) -> bool:
        """Read an answer into its question's field; True when it could be read."""
        match question.field:
            case "scope.regions":
                regions = self._resolver.mentions(text).regions or _resolved(
                    self._resolver.regions(text)
                )
                draft.regions = regions or draft.regions
                return bool(regions)
            case "scope.categories":
                categories = self._resolver.mentions(text).categories or _resolved(
                    self._resolver.categories(text)
                )
                draft.categories = categories or draft.categories
                return bool(categories)
            case "promo_window":
                return self._window_answer(text, draft)
            case "marketing_budget":
                amounts = _numbers(text, StatedKind.RUPEES)
                draft.budget = amounts[0] if amounts else draft.budget
                return bool(amounts)
            case "min_margin":
                shares = _numbers(text, StatedKind.PERCENT)
                draft.min_margin = shares[0] if shares else draft.min_margin
                return bool(shares)
            case "kvi_price_tolerance":
                shares = _numbers(text, StatedKind.PERCENT)
                draft.kvi_tolerance = shares[0] if shares else draft.kvi_tolerance
                return bool(shares)
            case "max_promoted_skus_per_category_per_region":
                count = re.search(r"\b\d{1,3}\b", text)
                draft.sku_cap = int(count.group()) if count else draft.sku_cap
                return count is not None
            case "clearance_targets":
                return self._clearance_answer(question, text, draft)
            case _:
                return True

    def _window_answer(self, text: str, draft: _Draft) -> bool:
        if _WEEKS.search(text) or len(self._resolver.mentions(text).holidays) == 1:
            self._window(text, draft)
            return True
        window = self._resolver.promo_window(text, regions=draft.regions or self._regions)
        if _resolved(window) is None:
            return False
        draft.weeks, draft.holiday = None, text  # `interpret` resolves the answer the same way
        return True

    def _clearance_answer(self, question: ClarificationQuestion, text: str, draft: _Draft) -> bool:
        shares = _numbers(text, StatedKind.PERCENT)
        products = self._products(text)
        if not shares and not products:
            return False
        index = question.id.partition(".")[2]
        known = draft.clearance
        if index.isdigit() and int(index) < len(known):
            ask = known[int(index)]
            known[int(index)] = ClearanceAsk(
                products=products or ask.products,
                sell_through=shares[0] if shares else ask.sell_through,
            )
        else:
            known.append(
                ClearanceAsk(products=products or text, sell_through=shares[0] if shares else None)
            )
        return True

    # --- the reading --------------------------------------------------------------------------

    def _reading(self, draft: _Draft) -> BriefReading:
        weeks = draft.weeks
        return BriefReading(
            regions=list(draft.regions) if draft.regions else None,
            regions_phrase=", ".join(r.value for r in draft.regions) if draft.regions else None,
            categories=list(draft.categories) if draft.categories else None,
            categories_phrase=", ".join(draft.categories) if draft.categories else None,
            sku_ids=list(draft.sku_ids) or None,
            promo_start_week=weeks[0] if weeks else None,
            promo_end_week=weeks[1] if weeks else None,
            holiday=draft.holiday,
            marketing_budget=draft.budget,
            min_margin=draft.min_margin,
            clearance=list(draft.clearance) or None,
            regional_budget_caps=[
                RegionalCap(region=region, cap=cap) for region, cap in draft.caps.items()
            ]
            or None,
            kvi_price_tolerance=draft.kvi_tolerance,
            max_promoted_skus_per_category_per_region=draft.sku_cap,
            objective_asked=draft.objective,
            segment_phrase=draft.segment,
        )


def _marked(assumption: Assumption) -> Assumption:
    """A fallback reading's assumption: marked, and at most `FALLBACK_CONFIDENCE` when the rules
    read it from the text."""
    read = assumption.source is AssumptionSource.BRIEF or assumption.field == "promo_window"
    update: dict[str, object] = {"fallback": True}
    if read and assumption.confidence > FALLBACK_CONFIDENCE:
        update["confidence"] = FALLBACK_CONFIDENCE
    if read and assumption.note is None:
        update["note"] = READ_BY_RULES
    return assumption.model_copy(update=update)


def _reworded(question: ClarificationQuestion, doubts: dict[str, _Doubt]) -> ClarificationQuestion:
    doubt = doubts.get(question.id)
    if doubt is None:
        return question
    text, reason, suggestions = doubt
    return question.model_copy(
        update={
            "question": text,
            "reason": reason,
            "suggestions": question.suggestions if suggestions is None else suggestions,
        }
    )


def _amendment_question(
    question_id: str, amendment: str, reply: str | None
) -> ClarificationQuestion:
    answered = f' The answer "{reply}" could not be read either.' if reply else ""
    return ClarificationQuestion(
        id=question_id,
        field=AMENDMENT,
        question=f'The language model is unavailable, and the amendment "{amendment}" could not '
        f"be read by rules.{answered} What should change? Name the regions or categories to "
        "drop or add, or the new budget, margin or weeks.",
        reason=QuestionReason.LOW_CONFIDENCE,
    )


def _sentences(text: str) -> list[str]:
    return [part for part in _SENTENCE_END.split(text) if part and part.strip()]


def _clauses(sentence: str) -> list[str]:
    return [part for part in _CLAUSE_BREAK.split(sentence) if part and part.strip()]


def _cue(clause: str, number: StatedNumber) -> str | None:
    """What a percentage is about: the nearest cue before it in its clause, else after it."""
    cues = sorted(
        (match.start(), match.end(), kind)
        for kind, pattern in (("margin", _MARGIN), ("clearance", _CLEARANCE), ("kvi", _KVI))
        for match in pattern.finditer(clause)
    )
    before = [kind for _, end, kind in cues if end <= number.start]
    after = [kind for start, _, kind in cues if start >= number.end]
    if before:
        return before[-1]
    return after[0] if after else None


def _in_order[T](order: Sequence[T], *parts: Sequence[T] | None) -> tuple[T, ...] | None:
    named = {item for part in parts for item in part or ()}
    return tuple(item for item in order if item in named) or None


def _without[T](kept: tuple[T, ...] | None, dropped: Sequence[T]) -> tuple[T, ...] | None:
    if kept is None:
        return None
    return tuple(item for item in kept if item not in dropped) or None


def _resolved[T](resolution: Resolution[T]) -> T | None:
    best = resolution.best
    return None if best is None or resolution.ambiguous else best.value


def _numbers(text: str, kind: StatedKind) -> list[float]:
    return [n.value for n in read_stated_numbers(text, bare=kind) if n.kind is kind]


def _add_clearance(draft: _Draft, ask: ClearanceAsk) -> None:
    for n, known in enumerate(draft.clearance):
        if known.products == ask.products:
            if ask.sell_through is not None or known.sell_through is None:
                draft.clearance[n] = ask
            return
    draft.clearance.append(ask)


def _objective(word: str) -> _Objective:
    return "revenue" if word.lower() in {"revenue", "turnover", "sales"} else "volume"


def _segment(text: str) -> str | None:
    match = _SEGMENT.search(text)
    if match is None:
        return None
    phrase = match.group(1).strip()
    if any(ch.isdigit() for ch in phrase) or _CLEARANCE.search(phrase) or _MARGIN.search(phrase):
        return None
    return phrase
