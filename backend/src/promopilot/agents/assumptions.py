"""The Context agent's deterministic half: an LLM reading of a brief → a planning request with
its assumptions, or the clarification questions to ask instead (AG-01, AG-02, ADR 0048).

- **Scope** comes from the brief's own phrases, resolved by `BriefResolver` (ADR 0032); a
  phrase's match score is the assumption's confidence. A phrase nothing matches, whose best
  reading scores below 0.7, or whose runner-up is within 0.1, is asked about.
- **The promo window** is the weeks the LLM picked from the week table when the brief says when
  (source brief), or the calendar's weeks of the holiday it names (source data).
- **Stated numbers** (budget, margin, targets, caps, tolerance) are the brief's, at confidence
  1. Unstated optional fields take company policy's value (source default).
- **A critical field** (marketing budget, regions, categories, promo window) that is missing
  or read below 0.7 is asked, never guessed. So is a clearance with no figure, or whose SKUs
  cannot be told (ADR 0040).
- **A brief value that would loosen company policy** stays in the request as read; planning
  applies the policy value (`guardrails.plan_limits`, ADR 0040), and the assumption shows the
  value applied and is flagged.
- **Data fills** the overstocked SKUs and undercut KVIs in scope, for the manager and planner.

No number here is computed by the LLM: every value is read, resolved or looked up.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final

import pandas as pd
import pydantic

from promopilot.agents.context import BriefError, BriefReading, week_table
from promopilot.agents.resolution import AMBIGUOUS_BELOW, BriefResolver, Resolution
from promopilot.agents.state import DegradedReason
from promopilot.competitors import competitor_gaps
from promopilot.domain import (
    Assumption,
    AssumptionSource,
    ClarificationQuestion,
    ClearanceTarget,
    CompanyPolicy,
    PlanningRequest,
    PolicyFinding,
    PromoWindow,
    QuestionReason,
    Region,
    Scope,
)
from promopilot.guardrails import plan_limits

CRITICAL_FIELDS: Final = {
    "marketing_budget": "marketing budget",
    "scope.regions": "regions",
    "scope.categories": "categories",
    "promo_window": "promo window",
}
"""The fields the agent must never guess (AG-02), with their names in words."""


@dataclass(frozen=True)
class ContextWorld:
    """What the Context agent checks a reading against, at the as-of week."""

    as_of_week: int
    as_of_date: str
    products: pd.DataFrame
    calendar: pd.DataFrame
    stock: pd.DataFrame | None
    """Pooled stock per SKU and region (`pooled_stock`); None without an inventory snapshot."""
    competitor_prices: pd.DataFrame
    policy: CompanyPolicy


@dataclass(frozen=True)
class ContextReading:
    """A brief as the Context agent read it: a planning request once nothing needs asking."""

    request: PlanningRequest | None
    """None while any question is open."""
    assumptions: tuple[Assumption, ...]
    questions: tuple[ClarificationQuestion, ...]
    degraded: DegradedReason | None = None
    """Why the brief was read by rules, not by the LLM (ADR 0053); None for an LLM reading."""


def interpret(reading: BriefReading, world: ContextWorld) -> ContextReading:
    """Resolve and check an LLM reading into a planning request, its assumptions and any
    questions. Raises `BriefError` only when the values cannot form a planning request at all."""
    return _Interpretation(reading, world).run()


def missing_fields_message(questions: Sequence[ClarificationQuestion]) -> str:
    """Why a reading is not a planning request yet, in words."""
    missing = [
        CRITICAL_FIELDS[q.field]
        for q in questions
        if q.reason is QuestionReason.MISSING and q.field in CRITICAL_FIELDS
    ]
    others = [
        q.question
        for q in questions
        if q.field not in CRITICAL_FIELDS or q.reason is not QuestionReason.MISSING
    ]
    parts = [f"the brief does not state: {', '.join(missing)}"] if missing else []
    parts.extend(others)
    return "; ".join(parts)


class _Interpretation:
    def __init__(self, reading: BriefReading, world: ContextWorld) -> None:
        self._reading = reading
        self._world = world
        self._policy = world.policy
        self._resolver = BriefResolver(world.products, world.calendar, world.as_of_week)
        self._table = week_table(world.calendar, world.as_of_week)
        known = set(world.calendar["region"])
        self._regions = [region for region in Region if region.value in known]
        self._categories = list(dict.fromkeys(world.products.sort_values("sku_id")["category"]))
        self._assumptions: list[Assumption] = []
        self._questions: list[ClarificationQuestion] = []

    def run(self) -> ContextReading:
        world = self._world
        self._assume(
            "as_of_week",
            f"week {world.as_of_week} (starts {world.as_of_date})",
            AssumptionSource.DATA,
            note="The latest week of history plus one: planning treats it as today.",
        )
        regions = self._scope_regions()
        categories = self._scope_categories()
        sku_ids = tuple(self._reading.sku_ids or ())
        if sku_ids:
            self._assume("scope.sku_ids", ", ".join(sku_ids), AssumptionSource.BRIEF)
        window = self._promo_window(regions)
        budget = self._marketing_budget()
        min_margin = self._min_margin()
        targets = self._clearance_targets(regions, categories)
        caps = self._regional_caps(regions)
        tolerance = self._kvi_tolerance()
        sku_cap = self._sku_cap()
        self._objective()
        self._segment()
        if regions is not None and categories is not None:
            self._overstocked(regions, categories)
            self._undercut(regions, categories)
        if (
            self._questions
            or regions is None
            or categories is None
            or window is None
            or budget is None
        ):
            return ContextReading(None, tuple(self._assumptions), tuple(self._questions))
        try:
            request = PlanningRequest(
                as_of_week=world.as_of_week,
                scope=Scope(regions=regions, categories=categories, sku_ids=sku_ids),
                promo_window=window,
                marketing_budget=budget,
                min_margin=min_margin,
                clearance_targets=targets,
                regional_budget_caps=caps,
                kvi_price_tolerance=tolerance,
                max_promoted_skus_per_category_per_region=sku_cap,
            )
        except pydantic.ValidationError as error:
            raise BriefError(
                f"the brief's reading is not a valid planning request: {error}"
            ) from error
        for finding in plan_limits(request, self._policy).findings:
            self._flag_finding(finding)
        return ContextReading(request, tuple(self._assumptions), ())

    # --- scope and window ---------------------------------------------------------------------

    def _scope_regions(self) -> tuple[Region, ...] | None:
        reading = self._reading
        phrase = reading.regions_phrase or ", ".join(r.value for r in reading.regions or ())
        every = tuple(r.value for r in self._regions)
        if not phrase.strip():
            self._ask(
                "scope.regions",
                "Which regions should the promotion run in?",
                QuestionReason.MISSING,
                every,
            )
            return None
        return self._resolved(
            "scope.regions",
            self._resolver.regions(phrase),
            f'Which regions does "{phrase}" mean?',
            every,
        )

    def _scope_categories(self) -> tuple[str, ...] | None:
        reading = self._reading
        phrase = reading.categories_phrase or ", ".join(reading.categories or ())
        if not phrase.strip():
            self._ask(
                "scope.categories",
                "Which product categories should the promotion cover?",
                QuestionReason.MISSING,
                tuple(self._categories),
            )
            return None
        return self._resolved(
            "scope.categories",
            self._resolver.categories(phrase),
            f'Which product categories does "{phrase}" mean?',
            tuple(self._categories),
        )

    def _promo_window(self, regions: tuple[Region, ...] | None) -> PromoWindow | None:
        reading = self._reading
        start, end = reading.promo_start_week, reading.promo_end_week
        weeks = sorted({int(w) for w in self._table["week_id"]})
        holidays = self._holiday_windows(regions)
        plannable = f"weeks {weeks[0]}-{weeks[-1]} can be planned" if weeks else "none"
        if start is not None and end is not None:
            if start not in weeks or end not in weeks or end < start:
                self._ask(
                    "promo_window",
                    "Which weeks should the promotion run? The brief reads as weeks "
                    f"{start}-{end}, but only {plannable}.",
                    QuestionReason.LOW_CONFIDENCE,
                    holidays,
                )
                return None
            named = f" ({reading.holiday})" if reading.holiday else ""
            self._assume("promo_window", f"weeks {start}-{end}{named}", AssumptionSource.BRIEF)
            return PromoWindow(start_week=start, end_week=end)
        if reading.holiday:
            return self._resolved(
                "promo_window",
                self._resolver.promo_window(reading.holiday, regions=regions or self._regions),
                f"Which weeks should the promotion run? The calendar has no clear match for "
                f'"{reading.holiday}" ({plannable}).',
                holidays,
                source=AssumptionSource.DATA,
                note="From the holiday calendar: the weeks it labels with the holiday.",
            )
        self._ask(
            "promo_window",
            f"When should the promotion run? {plannable.capitalize()}.",
            QuestionReason.MISSING,
            holidays,
        )
        return None

    def _holiday_windows(self, regions: tuple[Region, ...] | None) -> tuple[str, ...]:
        names = dict.fromkeys(str(n) for n in self._table["holiday_name"].dropna())
        labels = []
        for name in names:
            best = self._resolver.promo_window(name, regions=regions or self._regions).best
            if best is not None:
                labels.append(best.label)
        return tuple(labels)

    # --- numbers the brief states -------------------------------------------------------------

    def _marketing_budget(self) -> float | None:
        budget = self._reading.marketing_budget
        if budget is None:
            self._ask(
                "marketing_budget",
                "What marketing budget should the plan's promo cost stay within, in rupees?",
                QuestionReason.MISSING,
            )
            return None
        if budget <= 0:
            self._ask(
                "marketing_budget",
                f"The marketing budget reads as ₹{budget:,.0f}. What budget should the plan's "
                "promo cost stay within, in rupees?",
                QuestionReason.LOW_CONFIDENCE,
            )
            return None
        self._assume("marketing_budget", f"₹{budget:,.0f}", AssumptionSource.BRIEF)
        return budget

    def _min_margin(self) -> float | None:
        margin = self._reading.min_margin
        floor = self._policy.margin_floor
        if margin is None:
            self._assume(
                "min_margin",
                f"{floor:.1%} (the company-policy margin floor)",
                AssumptionSource.DEFAULT,
            )
            return None
        if not 0 <= margin < 1:
            self._ask(
                "min_margin",
                f"The minimum margin reads as {margin}. What blended margin should the plan keep, "
                "as a percentage?",
                QuestionReason.LOW_CONFIDENCE,
            )
            return None
        self._assume("min_margin", f"{margin:.1%}", AssumptionSource.BRIEF)
        return margin

    def _kvi_tolerance(self) -> float | None:
        tolerance = self._reading.kvi_price_tolerance
        policy = self._policy
        if tolerance is None:
            value = (
                f"{policy.kvi_price_tolerance:.1%} (company policy)"
                if policy.kvi_price_tolerance_enabled
                else "off (company policy)"
            )
            self._assume("kvi_price_tolerance", value, AssumptionSource.DEFAULT)
            return None
        if not 0 <= tolerance < 1:
            self._ask(
                "kvi_price_tolerance",
                f"The KVI price tolerance reads as {tolerance}. How far above the competitor may "
                "a KVI's promo price sit, as a percentage?",
                QuestionReason.LOW_CONFIDENCE,
            )
            return None
        self._assume("kvi_price_tolerance", f"{tolerance:.1%}", AssumptionSource.BRIEF)
        return tolerance

    def _sku_cap(self) -> int | None:
        cap = self._reading.max_promoted_skus_per_category_per_region
        field = "max_promoted_skus_per_category_per_region"
        if cap is None:
            policy_cap = self._policy.max_promoted_skus_per_category_per_region
            self._assume(field, f"{policy_cap} (company policy)", AssumptionSource.DEFAULT)
            return None
        if cap < 1:
            self._ask(
                field,
                f"The cap on promoted SKUs reads as {cap}. How many SKUs may be promoted per "
                "category in a region?",
                QuestionReason.LOW_CONFIDENCE,
            )
            return None
        self._assume(field, str(cap), AssumptionSource.BRIEF)
        return cap

    def _regional_caps(self, regions: tuple[Region, ...] | None) -> dict[Region, float]:
        asked = self._reading.regional_budget_caps or []
        if not asked:
            self._assume("regional_budget_caps", "none", AssumptionSource.DEFAULT)
            return {}
        caps: dict[Region, float] = {}
        dropped = []
        for cap in asked:
            if cap.cap <= 0 or (regions is not None and cap.region not in regions):
                dropped.append(f"{cap.region.value} ₹{cap.cap:,.0f}")
            else:
                caps[cap.region] = cap.cap
        value = ", ".join(f"{r.value} ₹{c:,.0f}" for r, c in caps.items()) or "none"
        note = (
            f"Dropped {', '.join(dropped)}: a cap must be positive and for a region in scope."
            if dropped
            else None
        )
        self._assume(
            "regional_budget_caps", value, AssumptionSource.BRIEF, flagged=bool(dropped), note=note
        )
        return caps

    # --- clearance ----------------------------------------------------------------------------

    def _clearance_targets(
        self, regions: tuple[Region, ...] | None, categories: tuple[str, ...] | None
    ) -> tuple[ClearanceTarget, ...]:
        asks = self._reading.clearance or []
        if not asks:
            self._assume("clearance_targets", "none", AssumptionSource.DEFAULT)
            return ()
        targets: dict[str, ClearanceTarget] = {}
        for n, ask in enumerate(asks):
            question_id = f"clearance_targets.{n}"
            resolution = self._resolver.products(ask.products, categories=categories)
            best = resolution.best
            if best is None or resolution.ambiguous:
                reason = (
                    QuestionReason.AMBIGUOUS
                    if best is not None and best.score >= AMBIGUOUS_BELOW
                    else QuestionReason.LOW_CONFIDENCE
                )
                suggestions = tuple(
                    c.label for c in resolution.candidates
                ) or self._overstocked_labels(regions, categories)
                self._ask(
                    "clearance_targets",
                    f'Which SKUs should be cleared when the brief says "{ask.products}"?',
                    reason,
                    suggestions,
                    question_id=question_id,
                )
                continue
            if ask.sell_through is None or not 0 < ask.sell_through <= 1:
                read_as = "" if ask.sell_through is None else f" It reads as {ask.sell_through}."
                self._ask(
                    "clearance_targets",
                    f'What sell-through should {best.label} ("{ask.products}") reach over the '
                    f"promo window, as a percentage of available stock?{read_as}",
                    QuestionReason.MISSING
                    if ask.sell_through is None
                    else QuestionReason.LOW_CONFIDENCE,
                    question_id=question_id,
                )
                continue
            skus = [sku for sku in best.value if sku not in targets]
            for sku in skus:
                targets[sku] = ClearanceTarget(sku_id=sku, sell_through=ask.sell_through)
            quiet = self._not_overstocked(skus, regions)
            self._assume(
                "clearance_targets",
                f"{ask.sell_through:.1%} sell-through for {best.label}: {', '.join(skus)}",
                AssumptionSource.BRIEF,
                confidence=best.score,
                flagged=bool(quiet),
                note=f"{', '.join(quiet)} not overstocked in any scope region at the as-of week; "
                "the target still applies."
                if quiet
                else None,
            )
        return tuple(targets.values())

    def _not_overstocked(
        self, skus: Sequence[str], regions: tuple[Region, ...] | None
    ) -> list[str]:
        stock = self._world.stock
        if stock is None or regions is None:
            return []
        scoped = stock[stock["region"].isin([r.value for r in regions]) & stock["is_overstock"]]
        overstocked = set(scoped["sku_id"])
        return [sku for sku in skus if sku not in overstocked]

    def _overstocked_rows(
        self, regions: Sequence[Region] | None, categories: Sequence[str] | None
    ) -> pd.DataFrame | None:
        stock = self._world.stock
        if stock is None:
            return None
        products = self._world.products
        rows = stock[stock["is_overstock"]]
        if regions is not None:
            rows = rows[rows["region"].isin([r.value for r in regions])]
        if categories is not None:
            in_categories = set(products[products["category"].isin(categories)]["sku_id"])
            rows = rows[rows["sku_id"].isin(in_categories)]
        names = products.set_index("sku_id")["name"]
        return rows.assign(name=rows["sku_id"].map(names)).sort_values(["sku_id", "region"])

    def _overstocked_labels(
        self, regions: Sequence[Region] | None, categories: Sequence[str] | None
    ) -> tuple[str, ...]:
        rows = self._overstocked_rows(regions, categories)
        if rows is None:
            return ()
        return tuple(
            f"{sku} {name}"
            for sku, name in dict(zip(rows["sku_id"], rows["name"], strict=True)).items()
        )

    # --- what the planner does not offer ------------------------------------------------------

    def _objective(self) -> None:
        asked = self._reading.objective_asked
        flagged = asked in ("revenue", "volume")
        self._assume(
            "objective",
            "incremental gross profit, net of cannibalisation and including halo",
            AssumptionSource.DEFAULT,
            flagged=flagged,
            note=f"The brief asks for {asked}; PromoPilot always maximises incremental profit "
            "(ADR 0005)."
            if flagged
            else None,
        )

    def _segment(self) -> None:
        phrase = self._reading.segment_phrase
        if not phrase:
            return
        self._assume(
            "target_segment",
            "chosen for each plan line by profit",
            AssumptionSource.DEFAULT,
            flagged=True,
            note=f'The brief asks to target "{phrase}"; the planner picks each plan line\'s '
            "target segment by expected profit, so other segments may be chosen.",
        )

    # --- data ---------------------------------------------------------------------------------

    def _overstocked(self, regions: tuple[Region, ...], categories: tuple[str, ...]) -> None:
        rows = self._overstocked_rows(regions, categories)
        if rows is None:
            return
        where: dict[str, list[str]] = {}
        for sku, region in zip(rows["sku_id"], rows["region"], strict=True):
            where.setdefault(str(sku), []).append(str(region))
        value = "; ".join(f"{sku} ({', '.join(r)})" for sku, r in where.items()) or "none"
        self._assume(
            "overstocked_skus",
            value,
            AssumptionSource.DATA,
            note="Days of cover above the company-policy threshold at the as-of week. They earn "
            "clearance value; only SKUs the brief names get a clearance target (ADR 0014).",
        )

    def _undercut(self, regions: tuple[Region, ...], categories: tuple[str, ...]) -> None:
        world = self._world
        gaps = competitor_gaps(
            world.products,
            world.competitor_prices,
            as_of_week=world.as_of_week,
            policy=self._policy,
            regions=regions,
            categories=categories,
            kvi_only=True,
        )
        undercut = [gap for gap in gaps.gaps if gap.undercut]
        value = (
            "; ".join(
                f"{gap.sku_id} in {gap.region.value} (competitor {gap.gap:.1%} cheaper)"
                for gap in undercut
            )
            or "none"
        )
        self._assume(
            "undercut_kvis",
            value,
            AssumptionSource.DATA,
            note="KVIs whose competitor price is below our base price by more than the "
            "company-policy undercut threshold; the planner may match them.",
        )

    # --- building blocks ----------------------------------------------------------------------

    def _resolved[T](
        self,
        field: str,
        resolution: Resolution[T],
        question: str,
        fallback: tuple[str, ...],
        *,
        source: AssumptionSource = AssumptionSource.BRIEF,
        note: str | None = None,
    ) -> T | None:
        best = resolution.best
        if best is not None and not resolution.ambiguous:
            self._assume(field, best.label, source, confidence=best.score, note=note)
            return best.value
        reason = (
            QuestionReason.AMBIGUOUS
            if best is not None and best.score >= AMBIGUOUS_BELOW
            else QuestionReason.LOW_CONFIDENCE
        )
        suggestions = tuple(c.label for c in resolution.candidates) or fallback
        self._ask(field, question, reason, suggestions)
        return None

    def _assume(
        self,
        field: str,
        value: str,
        source: AssumptionSource,
        *,
        confidence: float = 1.0,
        flagged: bool = False,
        note: str | None = None,
    ) -> None:
        self._assumptions.append(
            Assumption(
                field=field,
                value=value,
                source=source,
                confidence=confidence,
                flagged=flagged,
                note=note,
            )
        )

    def _ask(
        self,
        field: str,
        question: str,
        reason: QuestionReason,
        suggestions: tuple[str, ...] = (),
        *,
        question_id: str | None = None,
    ) -> None:
        self._questions.append(
            ClarificationQuestion(
                id=question_id or field,
                field=field,
                question=question,
                reason=reason,
                suggestions=suggestions,
            )
        )

    def _flag_finding(self, finding: PolicyFinding) -> None:
        shown: dict[str, Callable[[float], str]] = {
            "min_margin": lambda v: f"{v:.1%}",
            "max_promoted_skus_per_category_per_region": lambda v: f"{v:.0f}",
            "kvi_price_tolerance": lambda v: f"{v:.1%}",
        }
        show = shown.get(finding.field, str)
        for n, assumption in enumerate(self._assumptions):
            if assumption.field == finding.field:
                self._assumptions[n] = assumption.model_copy(
                    update={
                        "value": f"{show(finding.applied)} (company policy; the brief asked for "
                        f"{show(finding.requested)})",
                        "flagged": True,
                        "note": finding.message,
                    }
                )
