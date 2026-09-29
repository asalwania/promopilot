"""Agent-behaviour metrics (SPEC §12.2, #55, ADR 0062): evidence that the agent behaves.

- **Extraction accuracy**: each labelled planning-request field against the final request,
  by field matching rules (sets as sets, money within a rupee, fractions within a hundredth of
  a point, windows and counts exactly). A relaxation the session accepted changes the labels
  it touches first (ADR 0076).
- **Clarification behaviour**: a vague or conflicting scenario's session asks about, or flags,
  a field the scenario names; an ask no other scenario expects is counted as unneeded.
- **Infeasibility handling**: an infeasible scenario's final revision is `INFEASIBLE`, names
  what binds and proposes a relaxation (AG-06).
- **Grounding**: every Explainer run the LLM answered passed numeric grounding (ADR 0050).
- **P50 session latency and cost**: wall-clock time without fitting models, and the sum of the
  session's token-usage trace events (ADR 0047). Reported, with no target.

Each check reads one session's outcome and trace; each metric aggregates the checks of every
run as pure functions. The new expected properties are checked here too.
"""

import statistics
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from promopilot.competitors import CompetitorData, read_competitor_gaps
from promopilot.domain import (
    ClearanceTarget,
    CompanyPolicy,
    ConstraintKind,
    ExplanationSource,
    FallbackReason,
    PlanExplanation,
    PlanningRequest,
    PlanRevision,
    Relaxation,
    RelaxedConstraint,
    SessionUsage,
    SolveStatus,
    TokensUsed,
    TraceEvent,
)
from promopilot.evals.report import (
    ClarificationCheck,
    ExplainerRun,
    FieldMatch,
    InfeasibilityCheck,
    Metric,
    PropertyResult,
    RunOutcome,
    RunResult,
)
from promopilot.evals.scenarios import (
    AsksClarification,
    DiffChanges,
    FlagsAssumption,
    KviResponsePresent,
    RelaxationTouches,
    RequestLabels,
    Scenario,
    ScenarioGroup,
)

MONEY_TOLERANCE = 1.0
"""Rupees: a budget or cap read within a rupee of its label matches."""
FRACTION_TOLERANCE = 1e-4
"""A margin, tolerance or sell-through within a hundredth of a point of its label matches."""
_FLOAT_SLACK = 1e-9

EXTRACTION_TARGET = 0.95
CLARIFICATION_TARGET = 1.0
INFEASIBILITY_TARGET = 1.0
GROUNDING_TARGET = 0.98

type BehaviourProperty = RelaxationTouches | FlagsAssumption | DiffChanges | KviResponsePresent


# ---------------------------------------------------------------- extraction


def _close(tolerance: float) -> Callable[[float, float], bool]:
    return lambda label, got: abs(label - got) <= tolerance + _FLOAT_SLACK


_money = _close(MONEY_TOLERANCE)
_fraction = _close(FRACTION_TOLERANCE)


def _same_set(label: Iterable[Any], got: Iterable[Any]) -> bool:
    return set(label) == set(got)


def _same_mapping(close: Callable[[float, float], bool]) -> Callable[[Any, Any], bool]:
    def same(label: dict[Any, float], got: dict[Any, float]) -> bool:
        return label.keys() == got.keys() and all(close(label[k], got[k]) for k in label)

    return same


def _targets(targets: Iterable[Any]) -> dict[str, float]:
    return {target.sku_id: target.sell_through for target in targets}


def _optional(close: Callable[[float, float], bool]) -> Callable[[float, float | None], bool]:
    return lambda label, got: got is not None and close(label, got)


_RULES: dict[str, tuple[Callable[[PlanningRequest], Any], Callable[[Any, Any], bool]]] = {
    "regions": (lambda r: r.scope.regions, _same_set),
    "categories": (lambda r: r.scope.categories, _same_set),
    "sku_ids": (lambda r: r.scope.sku_ids, _same_set),
    "promo_window": (lambda r: r.promo_window, lambda label, got: label == got),
    "marketing_budget": (lambda r: r.marketing_budget, _money),
    "min_margin": (lambda r: r.min_margin, _optional(_fraction)),
    "clearance_targets": (
        lambda r: r.clearance_targets,
        lambda label, got: _same_mapping(_fraction)(_targets(label), _targets(got)),
    ),
    "regional_budget_caps": (lambda r: r.regional_budget_caps, _same_mapping(_money)),
    "kvi_price_tolerance": (lambda r: r.kvi_price_tolerance, _optional(_fraction)),
    "max_promoted_skus_per_category_per_region": (
        lambda r: r.max_promoted_skus_per_category_per_region,
        lambda label, got: label == got,
    ),
}


def match_fields(
    labels: RequestLabels,
    request: PlanningRequest | None,
    *,
    accepted: Sequence[Relaxation] = (),
) -> tuple[FieldMatch, ...]:
    """Each labelled field, in field order, against the final planning request; with no
    request every labelled field is wrong.

    The labels are what the scenario states. Each relaxation the session `accepted` replaces
    the labelled values it changes with its own, as the request read after the accept should
    hold them (ADR 0076); it never labels a field the scenario leaves out. A KVI tolerance it
    turns off is expected off."""
    matches = []
    for name, label in _relaxed_labels(labels, accepted).items():
        read, same = _RULES[name]
        got = None if request is None else read(request)
        matched = request is not None and (got is None if label is None else same(label, got))
        matches.append(
            FieldMatch(
                field=name,
                expected=_show(label),
                got=None if request is None else _show(got),
                matched=matched,
            )
        )
    return tuple(matches)


_RELAXES: dict[ConstraintKind, str] = {
    ConstraintKind.MARKETING_BUDGET: "marketing_budget",
    ConstraintKind.REGIONAL_BUDGET: "regional_budget_caps",
    ConstraintKind.MINIMUM_MARGIN: "min_margin",
    ConstraintKind.MAX_PROMOTED_SKUS: "max_promoted_skus_per_category_per_region",
    ConstraintKind.KVI_PRICE_TOLERANCE: "kvi_price_tolerance",
    ConstraintKind.CLEARANCE_TARGET: "clearance_targets",
}
"""The label each kind of relaxed constraint changes; company policy is never relaxed."""


def _relaxed_labels(labels: RequestLabels, accepted: Sequence[Relaxation]) -> dict[str, Any]:
    """The labelled fields, in field order, with each accepted change applied in turn."""
    expected = {
        name: getattr(labels, name)
        for name in RequestLabels.model_fields
        if getattr(labels, name) is not None
    }
    for change in (change for relaxation in accepted for change in relaxation.changes):
        name = _RELAXES.get(change.kind)
        if name is not None and name in expected:
            expected[name] = _relax(expected[name], change)
    return expected


def _relax(label: Any, change: RelaxedConstraint) -> Any:
    relaxed = change.relaxed
    match change.kind:
        case ConstraintKind.CLEARANCE_TARGET:
            targets: tuple[ClearanceTarget, ...] = label
            if relaxed is None:
                return tuple(t for t in targets if t.sku_id != change.sku_id)
            return tuple(
                t.model_copy(update={"sell_through": relaxed}) if t.sku_id == change.sku_id else t
                for t in targets
            )
        case ConstraintKind.REGIONAL_BUDGET:
            return label if change.region is None else {**label, change.region: relaxed}
        case ConstraintKind.MAX_PROMOTED_SKUS:
            return None if relaxed is None else round(relaxed)
        case _:
            return relaxed


def _show(value: Any) -> str:
    if value is None:
        return "none"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value)
    if isinstance(value, str | int):
        return str(getattr(value, "value", value))
    if isinstance(value, dict):
        return ", ".join(sorted(f"{_show(k)} {_show(v)}" for k, v in value.items())) or "none"
    if isinstance(value, tuple | list):
        return ", ".join(sorted(_show(item) for item in value)) or "none"
    if hasattr(value, "start_week"):
        return f"{value.start_week}-{value.end_week}"
    if hasattr(value, "sell_through"):
        return f"{value.sku_id} {_show(value.sell_through)}"
    return str(value)


def extraction_accuracy(runs: Sequence[RunResult]) -> Metric:
    """Correct labelled fields over labelled fields, across every run; the breakdown counts the
    misses per field. Target 95% (SPEC §12.2)."""
    matches = [match for run in runs for match in run.extraction]
    correct = sum(match.matched for match in matches)
    missed = Counter(match.field for match in matches if not match.matched)
    return _target_metric(
        "extraction_accuracy",
        "Extraction accuracy",
        correct,
        len(matches),
        EXTRACTION_TARGET,
        dict(missed),
    )


# ---------------------------------------------------------------- clarification


def _about(question_id: str, field: str) -> bool:
    """A question is about a field when its id is the field, or one of its items
    (`clearance_targets.0` is about `clearance_targets`)."""
    return question_id == field or question_id.startswith(f"{field}.")


def check_clarification(
    scenario: Scenario, *, asked: Sequence[str], flagged: Sequence[str]
) -> ClarificationCheck | None:
    """For a vague or conflicting scenario: whether its session asked about, or its final
    reading flags, a field the scenario names. None for any other scenario."""
    if scenario.group is not ScenarioGroup.VAGUE_OR_CONFLICTING:
        return None
    named = tuple(dict.fromkeys(scenario.clarified_fields))
    about = tuple(dict.fromkeys(q for q in asked if any(_about(q, f) for f in named)))
    flags = tuple(f for f in named if f in flagged)
    return ClarificationCheck(named=named, asked=about, flagged=flags, passed=bool(about or flags))


def unneeded_asks(scenario: Scenario, asked: Sequence[str]) -> tuple[str, ...]:
    """The questions a scenario outside the vague group does not expect to be asked."""
    if scenario.group is ScenarioGroup.VAGUE_OR_CONFLICTING:
        return ()
    expected = [p.asks_clarification for p in scenario.expect if isinstance(p, AsksClarification)]
    return tuple(dict.fromkeys(q for q in asked if not any(_about(q, f) for f in expected)))


def clarification_behaviour(runs: Sequence[RunResult]) -> Metric:
    """The share of vague or conflicting runs that ask or flag; target 100% (SPEC §12.2). The
    breakdown also counts the other runs with an unneeded ask, which has no target."""
    checks = [run.clarification for run in runs if run.clarification is not None]
    passed = sum(check.passed for check in checks)
    return _target_metric(
        "clarification_behaviour",
        "Clarification behaviour",
        passed,
        len(checks),
        CLARIFICATION_TARGET,
        {
            "asked": sum(bool(check.asked) for check in checks),
            "flagged_only": sum(bool(check.flagged and not check.asked) for check in checks),
            "neither": len(checks) - passed,
            "unneeded_asks": sum(bool(run.unneeded_asks) for run in runs),
        },
    )


# ---------------------------------------------------------------- infeasibility


def check_infeasibility(
    scenario: Scenario, revision: PlanRevision | None
) -> InfeasibilityCheck | None:
    """For an infeasible-constraints scenario: whether its final revision is `INFEASIBLE`,
    proposes a relaxation and names a binding constraint. A timeout, `FEASIBLE` with an
    unproven relaxation (ADR 0044), is not declared. None for any other scenario."""
    if scenario.group is not ScenarioGroup.INFEASIBLE_CONSTRAINTS:
        return None
    if revision is None:
        return InfeasibilityCheck(
            revision=None, declared=False, relaxation=False, binding_named=False, passed=False
        )
    declared = revision.solver_status is SolveStatus.INFEASIBLE
    relaxed = revision.relaxation is not None and bool(revision.relaxation.changes)
    binding = bool(revision.binding_constraints)
    return InfeasibilityCheck(
        revision=revision.number,
        declared=declared,
        relaxation=relaxed,
        binding_named=binding,
        passed=declared and relaxed and binding,
    )


def infeasibility_handling(runs: Sequence[RunResult]) -> Metric:
    """The share of infeasible-constraints runs declared infeasible with a relaxation and what
    binds; target 100% (SPEC §12.2). The breakdown counts each part that is missing."""
    checks = [run.infeasibility for run in runs if run.infeasibility is not None]
    planned = [check for check in checks if check.revision is not None]
    return _target_metric(
        "infeasibility_handling",
        "Infeasibility handling",
        sum(check.passed for check in checks),
        len(checks),
        INFEASIBILITY_TARGET,
        {
            "not_declared": sum(not check.declared for check in planned),
            "no_relaxation": sum(not check.relaxation for check in planned),
            "nothing_binds": sum(not check.binding_named for check in planned),
            "no_plan": len(checks) - len(planned),
        },
    )


# ---------------------------------------------------------------- grounding


def explainer_run(revision: int, explanation: PlanExplanation) -> ExplainerRun:
    return ExplainerRun(
        revision=revision,
        source=explanation.source,
        fallback_reason=explanation.fallback_reason,
    )


def grounding(runs: Sequence[RunResult]) -> Metric:
    """The share of Explainer runs the LLM answered whose explanation passed numeric grounding,
    after its one regeneration at most (ADR 0050); target 98% (SPEC §12.2).

    An LLM explanation passed; a template for an `ungrounded` or `invalid_answer` LLM answer
    failed. A template because the LLM was unavailable (a cassette miss included) checked
    nothing, so it is counted but not scored.
    """
    explained = [explanation for run in runs for explanation in run.explanations]
    reasons = Counter(
        "llm" if e.source is ExplanationSource.LLM else getattr(e.fallback_reason, "value", None)
        for e in explained
    )
    kinds = (
        "llm",
        FallbackReason.UNGROUNDED.value,
        FallbackReason.INVALID_ANSWER.value,
        FallbackReason.LLM_UNAVAILABLE.value,
    )
    breakdown = {kind: reasons[kind] for kind in kinds}
    scored = breakdown["llm"] + breakdown["ungrounded"] + breakdown["invalid_answer"]
    return _target_metric(
        "grounding", "Grounding", breakdown["llm"], scored, GROUNDING_TARGET, breakdown
    )


# ---------------------------------------------------------------- latency and cost


def session_usage(events: Iterable[TraceEvent]) -> SessionUsage:
    """What a session's LLM calls used and cost: the sums of its token-usage events, as the
    read model sums them (ADR 0047)."""
    used = [event.payload for event in events if isinstance(event.payload, TokensUsed)]
    return SessionUsage(
        calls=len(used),
        input_tokens=sum(u.input_tokens for u in used),
        output_tokens=sum(u.output_tokens for u in used),
        cost_usd=sum(u.cost_usd for u in used if u.cost_usd is not None),
        cost_inr=sum(u.cost_inr for u in used if u.cost_inr is not None),
        unpriced_models=tuple(dict.fromkeys(u.model for u in used if u.cost_usd is None)),
    )


def session_latency(runs: Sequence[RunResult]) -> Metric:
    """The median wall-clock session time of the runs that did not fail, without fitting
    models; reported, with no target (SPEC §12.2)."""
    timed = [run.session_s for run in runs if run.outcome is not RunOutcome.FAILED]
    return Metric(
        name="session_latency_p50",
        label="P50 session time",
        value=statistics.median(timed) if timed else None,
        count=len(timed),
        of=len(runs),
        breakdown={"max_s": round(max(timed))} if timed else {},
        unit="seconds",
    )


def session_cost(runs: Sequence[RunResult]) -> Metric:
    """The median LLM cost in rupees of the sessions that did not fail, from their token-usage
    events; reported, with no target (SPEC §12.2). A model with no configured price costs
    nothing here, and the breakdown counts the runs that used one."""
    costed = [run.usage for run in runs if run.outcome is not RunOutcome.FAILED]
    return Metric(
        name="session_cost_p50",
        label="P50 session cost",
        value=statistics.median(usage.cost_inr for usage in costed) if costed else None,
        count=len(costed),
        of=len(runs),
        breakdown={
            "calls": sum(usage.calls for usage in costed),
            "input_tokens": sum(usage.input_tokens for usage in costed),
            "output_tokens": sum(usage.output_tokens for usage in costed),
            "unpriced_runs": sum(bool(usage.unpriced_models) for usage in costed),
        },
        unit="rupees",
    )


def behaviour_metrics(runs: Sequence[RunResult]) -> tuple[Metric, ...]:
    """Every agent-behaviour metric, in report order."""
    return (
        extraction_accuracy(runs),
        clarification_behaviour(runs),
        infeasibility_handling(runs),
        grounding(runs),
        session_latency(runs),
        session_cost(runs),
    )


def _target_metric(
    name: str, label: str, count: int, of: int, target: float, breakdown: dict[str, int]
) -> Metric:
    value = None if of == 0 else count / of
    return Metric(
        name=name,
        label=label,
        value=value,
        count=count,
        of=of,
        target=target,
        direction="at_least",
        passed=None if value is None else value >= target,
        breakdown=breakdown,
    )


# ---------------------------------------------------------------- expected properties


async def kvi_response(
    data: CompetitorData,
    request: PlanningRequest,
    revision: PlanRevision,
    *,
    policy: CompanyPolicy,
) -> tuple[str, ...]:
    """The planner's response to the undercut KVIs in scope for this plan, recomputed from the
    competitor gaps as the planner computes it (F-08 AC2, ADR 0049); empty when none is
    undercut."""
    scope = request.scope
    gaps = await read_competitor_gaps(
        data,
        as_of_week=request.as_of_week,
        policy=policy,
        regions=scope.regions,
        categories=scope.categories,
        sku_ids=scope.sku_ids or None,
        kvi_only=True,
    )
    return gaps.undercut_response([planned.line for planned in revision.lines])


def check_behaviour_property(
    prop: BehaviourProperty,
    *,
    revision: PlanRevision | None,
    flagged: Sequence[str],
    notes: Sequence[str],
    summary: str | None,
    kvi: Sequence[str],
) -> PropertyResult:
    """Whether a session's outcome has one of #55's properties: its final revision, the fields
    its final reading flags, the planner's notes, the plan summary and the recomputed KVI
    response."""
    described = prop.describe()
    if isinstance(prop, FlagsAssumption):
        return PropertyResult(
            property=described,
            passed=prop.flags_assumption in flagged,
            detail=f"flagged {', '.join(flagged) or 'nothing'}",
        )
    if revision is None:
        return PropertyResult(property=described, passed=False, detail="no final plan revision")
    if isinstance(prop, RelaxationTouches):
        if revision.relaxation is None:
            return PropertyResult(
                property=described,
                passed=False,
                detail=f"revision {revision.number} has no relaxation",
            )
        kinds = tuple(dict.fromkeys(change.kind for change in revision.relaxation.changes))
        return PropertyResult(
            property=described,
            passed=prop.relaxation_touches in kinds,
            detail=f"revision {revision.number}'s relaxation changes "
            f"{', '.join(kind.value for kind in kinds) or 'nothing'}",
        )
    if isinstance(prop, DiffChanges):
        if revision.diff is None:
            return PropertyResult(
                property=described, passed=False, detail=f"revision {revision.number} has no diff"
            )
        fields = [change.field for change in revision.diff.request_changes]
        return PropertyResult(
            property=described,
            passed=prop.diff_changes in fields,
            detail=f"revision {revision.number}'s diff changes "
            f"{', '.join(fields) or 'no request field'}",
        )
    if not kvi:
        return PropertyResult(
            property=described, passed=False, detail="no KVI in scope is undercut"
        )
    from_notes = [sentence for sentence in kvi if sentence not in notes]
    from_summary = [sentence for sentence in kvi if summary is None or sentence not in summary]
    missing = [
        f"missing from the {where}: {' '.join(sentences)}"
        for where, sentences in (("notes", from_notes), ("summary", from_summary))
        if sentences
    ]
    return PropertyResult(
        property=described,
        passed=not missing,
        detail="; ".join(missing) or "the notes and the summary carry the KVI response",
    )
