"""The Explainer (SPEC §9.6, SF-05, ADR 0050): a summary of a plan revision and a rationale per
plan line, every number grounded in tool outputs.

The LLM writes them from a JSON view of the tool outputs in which every amount is already
shown as it may be cited (money in lakh or crore, percentages, whole units), so it never has to
calculate. `check_numeric_grounding` (ADR 0028) checks each part against that same view. An
answer that fails, or is blank or misses a plan line, is regenerated once with the problems
named; a second failure, or any `LLMError`, falls back to the deterministic template, which
only uses the revision's own numbers and always passes grounding.

For an infeasible revision, or when company policy binds, the summary opens with the
template's sentences on the binding constraints and the relaxation, whatever the LLM writes;
the planner's notes follow, then the LLM's summary.

A revision planned after an amendment carries its diff from the previous one (ADR 0052). The
LLM is then shown the diff and the planning-request changes, with every amount already shown,
and writes what changed and why in the same answer; the template writes it from the diff.
"""

import json
from collections.abc import Callable, Sequence
from importlib.resources import files
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

from promopilot.domain import (
    BindingConstraint,
    BindingEvidence,
    CompanyPolicy,
    ConstraintKind,
    ExplanationSource,
    FallbackReason,
    LineSimulation,
    Mechanism,
    MechanismOutcome,
    OpenIssue,
    Percentiles,
    PlanExplanation,
    PlanningRequest,
    PlanRevision,
    PlanRevisionLine,
    Region,
    RelaxedConstraint,
    RevisionDiff,
    SelectionReasonCode,
    SimulatedOutcomes,
    SolveStatus,
)
from promopilot.guardrails import (
    LineFacts,
    PlanFacts,
    check_numeric_grounding,
    format_percent,
    format_percentile,
    format_rupees,
    format_units,
)
from promopilot.llm import LLMError, LLMProvider, Message

ATTEMPTS: Final = 2
"""The first answer and one regeneration."""

MECHANISMS = {
    Mechanism.PCT_OFF: "% off",
    Mechanism.FIXED_PRICE: "fixed price",
    Mechanism.BOGO: "buy one get one",
    Mechanism.BUNDLE: "bundle",
}

_RUPEE_LIMITS = {ConstraintKind.MARKETING_BUDGET, ConstraintKind.REGIONAL_BUDGET}
_COUNT_LIMITS = {ConstraintKind.MAX_PROMOTED_SKUS}


class LineRationale(BaseModel):
    line: int = Field(description="The plan line's `line` number in the plan data.")
    rationale: str = Field(description="Why the line is in the plan: one or two sentences.")


def _every_field_required(schema: dict[str, Any]) -> None:
    # Structured outputs need every property required; `changes` keeps a Python default only
    # so answers built by hand need not name it. The LLM is never shown the default.
    properties = schema.get("properties", {})
    for field in properties.values():
        field.pop("default", None)
    schema["required"] = list(properties)


class ExplainerAnswer(BaseModel):
    """What the Explainer's LLM writes for a plan revision."""

    model_config = ConfigDict(json_schema_extra=_every_field_required)

    summary: str = Field(description="The plan summary: two to five sentences.")
    rationales: list[LineRationale] = Field(description="One rationale for every plan line.")
    changes: str | None = Field(
        default=None,
        description="What changed from the previous plan revision and why: two to four "
        "sentences; null when the plan data has no changes_from_previous.",
    )


def explainer_prompt() -> str:
    return (files("promopilot.agents") / "prompts" / "explainer.md").read_text("utf-8")


async def explain_plan(
    llm: LLMProvider,
    revision: PlanRevision,
    *,
    request: PlanningRequest,
    policy: CompanyPolicy,
    facts: PlanFacts | None = None,
    open_issues: tuple[OpenIssue, ...] = (),
    notes: tuple[str, ...] = (),
) -> PlanExplanation:
    """The LLM's grounded explanation of `revision`, or the template's when it cannot give one.

    Never raises for an LLM failure: the template records why it was used instead.
    """
    data = plan_data(
        revision, request=request, policy=policy, facts=facts, open_issues=open_issues, notes=notes
    )
    messages = [
        Message(role="system", content=explainer_prompt()),
        Message(
            role="user",
            content="Plan data (JSON from PromoPilot's deterministic tools):\n"
            f"{json.dumps(data, ensure_ascii=False)}",
        ),
    ]
    reason = FallbackReason.LLM_UNAVAILABLE
    for _ in range(ATTEMPTS):
        try:
            answer = await llm.complete_structured(ExplainerAnswer, messages)
        except LLMError:
            reason = FallbackReason.LLM_UNAVAILABLE
            break
        rationales = _rationales(answer, revision)
        problems = _structure_problems(answer, rationales, revision.diff)
        reason = FallbackReason.INVALID_ANSWER
        if not problems:
            problems = _grounding_problems(answer, data, revision.diff)
            reason = FallbackReason.UNGROUNDED
        if not problems and rationales is not None:
            return PlanExplanation(
                summary=" ".join([*_opening(revision, notes), answer.summary.strip()]),
                rationales=rationales,
                source=ExplanationSource.LLM,
                changes=None if revision.diff is None else (answer.changes or "").strip(),
            )
        messages = [
            *messages,
            Message(role="assistant", content=answer.model_dump_json()),
            Message(role="user", content=_feedback(problems)),
        ]
    template = template_explanations(revision, open_issues, notes)
    return template.model_copy(update={"fallback_reason": reason})


def template_explanations(
    revision: PlanRevision,
    open_issues: tuple[OpenIssue, ...] = (),
    notes: tuple[str, ...] = (),
) -> PlanExplanation:
    """The deterministic explanation: only the revision's own numbers, and the planner's notes
    verbatim, so its numbers always pass grounding against the revision."""
    return PlanExplanation(
        summary=_summary(revision, open_issues, notes),
        rationales=tuple(_rationale(planned) for planned in revision.lines),
        source=ExplanationSource.TEMPLATE,
        changes=None if revision.diff is None else _changes(revision.number, revision.diff),
    )


# ---------------------------------------------------------------- the LLM's answer


def _rationales(answer: ExplainerAnswer, revision: PlanRevision) -> tuple[str, ...] | None:
    """The answer's rationales in plan-line order; None unless each line has exactly one."""
    numbers = [number for number, _ in enumerate(revision.lines, start=1)]
    if sorted(item.line for item in answer.rationales) != numbers:
        return None
    written = {item.line: item.rationale.strip() for item in answer.rationales}
    return tuple(written[number] for number in numbers)


def _structure_problems(
    answer: ExplainerAnswer, rationales: tuple[str, ...] | None, diff: RevisionDiff | None
) -> list[str]:
    problems = []
    if not answer.summary.strip():
        problems.append("the summary is blank")
    if diff is not None and not (answer.changes or "").strip():
        problems.append(
            f"write changes: what changed from plan revision {diff.from_revision} and why"
        )
    if rationales is None:
        written = [item.line for item in answer.rationales]
        problems.append(
            "write exactly one rationale for every plan line, by its `line` number; you wrote "
            f"rationales for lines {written}"
        )
    else:
        problems += [
            f"the rationale for line {number} is blank"
            for number, text in enumerate(rationales, start=1)
            if not text
        ]
    return problems


def _grounding_problems(
    answer: ExplainerAnswer, data: object, diff: RevisionDiff | None
) -> list[str]:
    parts = [
        ("the summary", answer.summary),
        *((f"the rationale for line {item.line}", item.rationale) for item in answer.rationales),
    ]
    if diff is not None:
        parts.append(("what changed", answer.changes or ""))
    problems = []
    for where, text in parts:
        report = check_numeric_grounding(text, data)
        if not report.grounded:
            cited = ", ".join(report.ungrounded)
            problems.append(f"{where} cites numbers the plan data does not show: {cited}")
    return problems


def _feedback(problems: Sequence[str]) -> str:
    listed = "\n".join(f"- {problem}" for problem in problems)
    return (
        f"Your answer failed PromoPilot's checks:\n{listed}\n"
        "Write the whole answer again. Copy every number exactly as the plan data shows it, "
        "write one rationale for every plan line, and, when the plan data has "
        "changes_from_previous, say what changed and why."
    )


# ---------------------------------------------------------------- what the LLM is shown


def plan_data(
    revision: PlanRevision,
    *,
    request: PlanningRequest,
    policy: CompanyPolicy,
    facts: PlanFacts | None = None,
    open_issues: tuple[OpenIssue, ...] = (),
    notes: tuple[str, ...] = (),
) -> dict[str, object]:
    """The tool outputs the LLM explains and its numbers are grounded against, every amount
    shown as it may be cited.

    Binding constraints the optimiser could not prove, and how much each proven one is
    worth, are left out: time-limited re-solves settle them differently on different
    machines (ADR 0038), and the request must hash the same everywhere to replay (ADR 0019).
    """
    simulated = _line_simulations(revision)
    line_facts = (
        {(fact.line.sku_id, fact.line.region): fact for fact in facts.lines} if facts else {}
    )
    changes = {} if revision.diff is None else {"changes_from_previous": _diff_data(revision.diff)}
    return {
        "plan_revision": revision.number,
        "solver_status": None if revision.solver_status is None else revision.solver_status.value,
        "objective": None if revision.objective is None else format_rupees(revision.objective),
        "plan_line_count": len(revision.lines),
        "safety_margin": _safety_data(revision),
        "lines": [
            _line_data(
                number,
                planned,
                simulated.get((planned.line.sku_id, planned.line.region)),
                line_facts.get((planned.line.sku_id, planned.line.region)),
            )
            for number, planned in enumerate(revision.lines, start=1)
        ],
        "plan_simulation": None
        if revision.simulation is None
        else {
            **_outcomes(revision.simulation.total),
            "stockout_probability_by_region": {
                region.region.value: format_percent(region.stockout_probability)
                for region in revision.simulation.regions
            },
        },
        "binding_constraints": [
            {
                "constraint": _constraint(
                    binding.kind, binding.region, binding.sku_id, binding.category
                ),
                "source": binding.source.value,
                "limit": _limit(binding.kind, binding.limit),
            }
            for binding in _proven(revision.binding_constraints)
        ],
        "clearance_shortfalls": [
            {
                "sku_id": shortfall.sku_id,
                "region": shortfall.region.value,
                "target": format_percent(shortfall.target),
                "expected_sell_through": format_percent(shortfall.expected_sell_through),
                "shortfall_units": format_units(shortfall.shortfall_units),
            }
            for shortfall in revision.clearance_shortfalls
        ],
        "relaxation": None
        if revision.relaxation is None
        else {
            "policy_binds": revision.relaxation.policy_binds,
            "proven": revision.relaxation.proven,
            "changes": [_change_data(change) for change in revision.relaxation.changes],
        },
        "policy_findings": [finding.message for finding in revision.policy_findings],
        "open_issues": [issue.message for issue in open_issues],
        "planner_notes": list(notes),
        "options_left_out": [
            {
                "sku_id": left_out.option.sku_id,
                "region": left_out.option.region.value,
                "mechanism": left_out.option.mechanism.value,
                "depth": f"{left_out.option.depth_pct}%",
                "value": format_rupees(left_out.value),
                "reasons": [reason.value for reason in left_out.reasons],
                "cannibalises": list(left_out.cannibalises),
            }
            for left_out in revision.not_selected
        ],
        "planning_request": {
            "regions": [region.value for region in request.scope.regions],
            "categories": list(request.scope.categories),
            "sku_ids": list(request.scope.sku_ids),
            "promo_window": f"W{request.promo_window.start_week} to "
            f"W{request.promo_window.end_week}",
            "marketing_budget": format_rupees(request.marketing_budget),
            "min_margin": None
            if request.min_margin is None
            else format_percent(request.min_margin),
            "clearance_targets": {
                target.sku_id: format_percent(target.sell_through)
                for target in request.clearance_targets
            },
            "regional_budget_caps": {
                region.value: format_rupees(cap)
                for region, cap in request.regional_budget_caps.items()
            },
            "max_promoted_skus_per_category_per_region": (
                request.max_promoted_skus_per_category_per_region
            ),
        },
        "company_policy": {
            "margin_floor": format_percent(policy.margin_floor),
            "max_discount": f"{policy.max_discount_pct}%",
            "max_promoted_skus_per_category_per_region": (
                policy.max_promoted_skus_per_category_per_region
            ),
        },
        **changes,
    }


def _diff_data(diff: RevisionDiff) -> dict[str, object]:
    """The diff from the previous revision, every amount shown as it may be cited. The
    amendment's own words are not in it: the request changes say what it changed (ADR 0052)."""
    return {
        "from_revision": diff.from_revision,
        "request_changes": [change.model_dump() for change in diff.request_changes],
        "lines_added": [_diff_line(planned) for planned in diff.added],
        "lines_removed": [_diff_line(planned) for planned in diff.removed],
        "lines_changed": [
            {
                "sku_id": change.sku_id,
                "region": change.region.value,
                "changed": list(change.fields),
                "before": _diff_line(change.before),
                "after": _diff_line(change.after),
            }
            for change in diff.changed
        ],
        "line_counts": {
            "added": len(diff.added),
            "removed": len(diff.removed),
            "changed": len(diff.changed),
            "unchanged": diff.unchanged,
        },
        "objective": None
        if diff.objective_delta is None
        else _delta_data(diff.objective_before, diff.objective_after, diff.objective_delta),
        "promo_cost": _delta_data(
            diff.promo_cost_before, diff.promo_cost_after, diff.promo_cost_delta
        ),
    }


def _diff_line(planned: PlanRevisionLine) -> dict[str, object]:
    line = planned.line
    return {
        "sku_id": line.sku_id,
        "region": line.region.value,
        "mechanism": line.mechanism.value,
        "depth": f"{line.depth_pct}%",
        "weeks": line.duration_weeks,
        "start_week": f"W{line.start_week}",
        "target_segment": line.target_segment.value,
        "promo_cost": format_rupees(planned.promo_cost),
        "expected_incremental_profit": format_rupees(planned.expected_incremental_profit),
    }


def _delta_data(before: float | None, after: float | None, delta: float) -> dict[str, object]:
    return {
        "before": None if before is None else format_rupees(before),
        "after": None if after is None else format_rupees(after),
        "change": format_rupees(delta),
    }


def _line_data(
    number: int,
    planned: PlanRevisionLine,
    simulated: LineSimulation | None,
    facts: LineFacts | None,
) -> dict[str, object]:
    line = planned.line
    why = planned.why_chosen
    return {
        "line": number,
        "sku_id": line.sku_id,
        "region": line.region.value,
        "mechanism": line.mechanism.value,
        "depth": f"{line.depth_pct}%",
        "bundle_partner_sku_id": line.bundle_partner_sku_id,
        "weeks": line.duration_weeks,
        "start_week": f"W{line.start_week}",
        "target_segment": line.target_segment.value,
        "expected_units": format_units(planned.expected_units),
        "promo_cost": format_rupees(planned.promo_cost),
        "expected_incremental_profit": format_rupees(planned.expected_incremental_profit),
        "why_chosen": None
        if why is None
        else {
            "value": format_rupees(why.value),
            "best_option_for_sku_and_region": why.best_for_sku_region,
            "reasons": {
                reason.code.value: f"{format_units(reason.amount)} units"
                if reason.code is SelectionReasonCode.CLEARANCE_TARGET
                else format_rupees(reason.amount)
                for reason in why.reasons
            },
        },
        "mechanisms_compared": [
            _mechanism_data(outcome) for outcome in planned.mechanism_comparison
        ],
        "simulated": None
        if simulated is None
        else {
            "units": _range(simulated.units, format_units),
            "gross_profit": _range(simulated.gross_profit, format_rupees),
            "stockout_probability": format_percent(simulated.stockout_probability),
        },
        "plan_time_facts": None
        if facts is None
        else {
            "base_price": format_rupees(facts.anchor.base_price),
            "p90_units": format_units(facts.p90_units),
            "available_stock": format_units(facts.available_stock),
            "expected_revenue": format_rupees(facts.expected_revenue),
            "expected_gross_profit": format_rupees(facts.expected_gross_profit),
        },
    }


def _mechanism_data(outcome: MechanismOutcome) -> dict[str, object]:
    best = outcome.best
    if best is None:
        return {
            "mechanism": outcome.mechanism.value,
            "unavailable": [reason.value for reason in outcome.unavailable],
        }
    return {
        "mechanism": outcome.mechanism.value,
        "chosen": outcome.chosen,
        "depth": f"{best.option.depth_pct}%",
        "value": format_rupees(best.value),
        "incremental_profit": format_rupees(best.incremental_profit),
        "margin": format_percent(best.margin),
    }


def _outcomes(outcomes: SimulatedOutcomes) -> dict[str, object]:
    return {
        "units": _range(outcomes.units, format_units),
        "revenue": _range(outcomes.revenue, format_rupees),
        "gross_profit": _range(outcomes.gross_profit, format_rupees),
        "margin": _range(outcomes.margin, format_percent),
        "promo_spend": _range(outcomes.promo_spend, format_rupees),
    }


def _range(percentiles: Percentiles, show: Callable[[float], str]) -> dict[str, str]:
    return {
        "p10": show(percentiles.p10),
        "p50": show(percentiles.p50),
        "p90": show(percentiles.p90),
    }


def _line_simulations(revision: PlanRevision) -> dict[tuple[str, Region], LineSimulation]:
    if revision.simulation is None:
        return {}
    return {(line.sku_id, line.region): line for line in revision.simulation.lines}


def _change_data(change: RelaxedConstraint) -> dict[str, object]:
    return {
        "constraint": _constraint(change.kind, change.region, change.sku_id, None),
        "from": _limit(change.kind, change.current),
        "to": "dropped" if change.relaxed is None else _limit(change.kind, change.relaxed),
        "change": format_percent(change.change),
        "policy_allows": None
        if change.policy_allows is None
        else format_percent(change.policy_allows),
    }


# ---------------------------------------------------------------- the template


def _rationale(planned: PlanRevisionLine) -> str:
    line = planned.line
    partner = "" if line.bundle_partner_sku_id is None else f" with {line.bundle_partner_sku_id}"
    weeks = "week" if line.duration_weeks == 1 else "weeks"
    return (
        f"{line.sku_id} in {line.region.value}: {MECHANISMS[line.mechanism]}{partner} at "
        f"{line.depth_pct}% for {line.duration_weeks} {weeks} from W{line.start_week}, for "
        f"{line.target_segment.value}. Expected {format_units(planned.expected_units)} units, "
        f"promo cost {format_rupees(planned.promo_cost)}, expected incremental profit "
        f"{format_rupees(planned.expected_incremental_profit)}."
    )


def _summary(
    revision: PlanRevision, open_issues: tuple[OpenIssue, ...], notes: tuple[str, ...]
) -> str:
    parts = [f"Plan revision {revision.number}."]
    status = revision.solver_status
    if status is SolveStatus.INFEASIBLE and revision.relaxation and not revision.relaxation.proven:
        # Not proven: the solver's work ran out first (ADR 0074).
        parts.append(
            "Infeasible: no plan found within the optimiser's work budget reaches every "
            "clearance target, so this is the closest plan found."
        )
    elif status is SolveStatus.INFEASIBLE:
        parts.append(
            "Infeasible: no plan reaches every clearance target within the brief's "
            "constraints, so this is the closest plan."
        )
    elif not revision.lines and status is SolveStatus.OPTIMAL:
        parts.append("No promo option pays for itself within the brief's constraints.")
    elif not revision.lines:
        parts.append("No plan was found within the optimiser's work budget.")
    elif status is SolveStatus.OPTIMAL:
        parts.append("The optimiser proved this plan the most profitable within the constraints.")
    else:
        parts.append(
            "The optimiser found this plan within its time limit, without proving it best."
        )
    if revision.objective is not None and revision.lines:
        parts.append(f"Its objective is {format_rupees(revision.objective)}.")
    parts += _safety_sentences(revision)
    parts += _constraint_sentences(revision)
    parts += notes
    if open_issues:
        codes = sorted({issue.code.value for issue in open_issues})
        parts.append(f"Open issues the critic found: {', '.join(codes)}.")
    return " ".join(parts)


_REQUEST_FIELDS = {
    "as_of_week": "the as-of week",
    "scope.regions": "the regions",
    "scope.categories": "the categories",
    "scope.sku_ids": "the SKUs",
    "promo_window": "the promo window",
    "marketing_budget": "the marketing budget",
    "min_margin": "the minimum margin",
    "clearance_targets": "the clearance targets",
    "regional_budget_caps": "the regional budget caps",
    "kvi_price_tolerance": "the KVI price tolerance",
    "max_promoted_skus_per_category_per_region": "the cap on promoted SKUs per category and region",
}


def _changes(number: int, diff: RevisionDiff) -> str:
    """What changed from the previous revision, in the diff's own numbers (ADR 0052)."""
    parts = [f"Plan revision {number} changes plan revision {diff.from_revision}."]
    if diff.request_changes:
        named = [
            f"{_REQUEST_FIELDS.get(change.field, change.field)} from {change.before} to "
            f"{change.after}"
            for change in diff.request_changes
        ]
        parts.append(f"The planning request changed: {'; '.join(named)}.")
    else:
        parts.append("The planning request did not change.")
    if diff.added:
        parts.append(f"Added: {_places(diff.added)}.")
    if diff.removed:
        parts.append(f"Removed: {_places(diff.removed)}.")
    if diff.changed:
        named = [
            f"{change.sku_id} in {change.region.value} ({', '.join(change.fields)})"
            for change in diff.changed
        ]
        parts.append(f"Changed: {', '.join(named)}.")
    if diff.unchanged:
        lines = "plan line is" if diff.unchanged == 1 else "plan lines are"
        parts.append(f"{format_units(diff.unchanged)} {lines} unchanged.")
    promo_cost = (
        f"the promo cost from {format_rupees(diff.promo_cost_before)} to "
        f"{format_rupees(diff.promo_cost_after)} ({_moved(diff.promo_cost_delta)})"
    )
    if diff.objective_delta is None:
        parts.append(f"{promo_cost[0].upper()}{promo_cost[1:]}.")
    else:
        parts.append(
            f"The objective goes from {_rupees(diff.objective_before)} to "
            f"{_rupees(diff.objective_after)} ({_moved(diff.objective_delta)}), and {promo_cost}."
        )
    return " ".join(parts)


def _places(lines: tuple[PlanRevisionLine, ...]) -> str:
    return ", ".join(f"{planned.line.sku_id} in {planned.line.region.value}" for planned in lines)


def _rupees(amount: float | None) -> str:
    return "nothing" if amount is None else format_rupees(amount)


def _moved(delta: float) -> str:
    # The sign is written as a word; grounding ignores signs (ADR 0028).
    shown = format_rupees(delta).removeprefix("-")
    if shown == "₹0":
        return "unchanged"
    return f"down {shown}" if delta < 0 else f"up {shown}"


def _opening(revision: PlanRevision, notes: tuple[str, ...]) -> list[str]:
    """The sentences every summary opens with, whoever writes the rest."""
    relaxation = revision.relaxation
    policy_binds = relaxation is not None and relaxation.policy_binds
    if revision.solver_status is SolveStatus.INFEASIBLE or policy_binds:
        return [*_constraint_sentences(revision), *notes]
    return list(notes)


def _constraint_sentences(revision: PlanRevision) -> list[str]:
    sentences = []
    proven = _proven(revision.binding_constraints)
    if proven:
        named = [
            f"{_constraint(b.kind, b.region, b.sku_id, b.category)} at {_limit(b.kind, b.limit)}"
            for b in proven
        ]
        sentences.append(f"Binding constraints: {'; '.join(named)}.")
    unproven = [b for b in revision.binding_constraints if b.evidence is BindingEvidence.UNPROVEN]
    if unproven:
        named = [_constraint(b.kind, b.region, b.sku_id, b.category) for b in unproven]
        sentences.append(f"These may also bind: {'; '.join(named)}.")
    sentences += [
        f"{shortfall.sku_id} in {shortfall.region.value} is expected to reach "
        f"{format_percent(shortfall.expected_sell_through)} sell-through against a "
        f"{format_percent(shortfall.target)} target, "
        f"{format_units(shortfall.shortfall_units)} units short."
        for shortfall in revision.clearance_shortfalls
    ]
    relaxation = revision.relaxation
    if relaxation is not None and relaxation.changes:
        changes = [_change_text(change) for change in relaxation.changes]
        sentences.append(f"The smallest relaxation: {'; '.join(changes)}.")
        if relaxation.policy_binds:
            sentences.append(
                "Company policy binds: no change to the brief alone reaches the targets."
            )
            sentences += [
                f"Within company policy, {change.sku_id} can reach at most "
                f"{format_percent(change.policy_allows)} sell-through."
                for change in relaxation.changes
                if change.policy_allows is not None and change.sku_id is not None
            ]
    return sentences


def _safety_sentences(revision: PlanRevision) -> list[str]:
    """What the budget counted with the plan's safety margin, or that it was waived for the
    clearance targets (ADR 0080)."""
    margin = revision.safety_margin
    if margin is None or not revision.lines:
        return []
    if margin.budget_margin_waived:
        return [
            "The budget is planned at the expected promo cost, without a safety margin: the "
            "clearance targets need all of it."
        ]
    if margin.budget_quantile <= 0.5:
        return []
    return [
        f"With its safety margin, the plan's promo cost at its "
        f"{format_percentile(margin.budget_quantile)} is "
        f"{format_rupees(margin.planned_promo_cost)} against the marketing budget."
    ]


def _safety_data(revision: PlanRevision) -> dict[str, object] | None:
    """The safety margin the plan keeps from its limits, as it may be cited (ADR 0080)."""
    margin = revision.safety_margin
    if margin is None:
        return None
    budget = (
        "at the expected promo cost, waived: the clearance targets need the whole budget"
        if margin.budget_margin_waived
        else f"promo cost at its {format_percentile(margin.budget_quantile)}"
    )
    return {
        "budget": budget,
        "planned_promo_cost": format_rupees(margin.planned_promo_cost),
        "stock": f"expected units plus {margin.stock_sigmas:g} std within available stock",
        "margin": f"blended margin with units at their {format_percentile(margin.margin_quantile)}",
    }


def _change_text(change: RelaxedConstraint) -> str:
    name = _constraint(change.kind, change.region, change.sku_id, None)
    current = _limit(change.kind, change.current)
    if change.relaxed is None:
        return f"drop {name} ({current})"
    return f"{name} from {current} to {_limit(change.kind, change.relaxed)}"


def _proven(bindings: tuple[BindingConstraint, ...]) -> list[BindingConstraint]:
    return [b for b in bindings if b.evidence is not BindingEvidence.UNPROVEN]


def _constraint(
    kind: ConstraintKind, region: Region | None, sku_id: str | None, category: str | None
) -> str:
    where = "" if region is None else f" in {region.value}"
    match kind:
        case ConstraintKind.MARKETING_BUDGET:
            return "the marketing budget"
        case ConstraintKind.REGIONAL_BUDGET:
            return f"the budget cap{where}"
        case ConstraintKind.MINIMUM_MARGIN:
            return "the minimum margin"
        case ConstraintKind.MARGIN_FLOOR:
            return "the company-policy margin floor"
        case ConstraintKind.MAX_PROMOTED_SKUS:
            of = "" if category is None else f" {category}"
            scope = where or " per category and region"
            return f"the cap on promoted{of} SKUs{scope}"
        case ConstraintKind.CLEARANCE_TARGET:
            return f"the clearance target for {sku_id}{where}"
        case ConstraintKind.KVI_PRICE_TOLERANCE:
            return "the KVI price tolerance"
        case ConstraintKind.STRONG_SUBSTITUTES:
            return "the rule against promoting strong substitutes together"


def _limit(kind: ConstraintKind, value: float) -> str:
    if kind in _RUPEE_LIMITS:
        return format_rupees(value)
    if kind in _COUNT_LIMITS:
        return f"{format_units(value)} SKUs"
    if kind is ConstraintKind.STRONG_SUBSTITUTES:
        # The least estimated cross-price effect of a strong pair (ADR 0075).
        return f"θ {value:.2f}"
    return format_percent(value)
