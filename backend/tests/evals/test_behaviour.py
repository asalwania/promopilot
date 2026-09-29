"""Agent-behaviour metrics on hand-built inputs (SPEC §12.2, #55, ADR 0062): extraction accuracy
with its field matching rules, clarification behaviour, infeasibility handling, grounding, and
P50 session latency and cost."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from promopilot.domain import (
    BindingConstraint,
    BindingEvidence,
    ClearanceTarget,
    ConstraintKind,
    ConstraintSource,
    ExplanationSource,
    FallbackReason,
    NodeStarted,
    PlanExplanation,
    PlanningRequest,
    PlanRevision,
    PromoWindow,
    Region,
    Relaxation,
    RelaxedConstraint,
    RequestChange,
    RevisionDiff,
    Scope,
    SessionUsage,
    SolveStatus,
    TokensUsed,
    TraceEvent,
)
from promopilot.evals import (
    DiffChanges,
    FlagsAssumption,
    KviResponsePresent,
    RelaxationTouches,
    RequestLabels,
    Scenario,
)
from promopilot.evals.behaviour import (
    check_clarification,
    check_infeasibility,
    clarification_behaviour,
    explainer_run,
    extraction_accuracy,
    grounding,
    infeasibility_handling,
    match_fields,
    session_cost,
    session_latency,
    session_usage,
    unneeded_asks,
)
from promopilot.evals.metrics import check_property
from promopilot.evals.report import (
    ClarificationCheck,
    ExplainerRun,
    FieldMatch,
    InfeasibilityCheck,
    RunOutcome,
    RunResult,
)

REQUEST = PlanningRequest(
    as_of_week=104,
    scope=Scope(regions=(Region.NORTH, Region.WEST), categories=("Snacks", "Beverages")),
    promo_window=PromoWindow(start_week=108, end_week=109),
    marketing_budget=200_000.4,
    min_margin=0.18,
    clearance_targets=(
        ClearanceTarget(sku_id="SKU0006", sell_through=0.6),
        ClearanceTarget(sku_id="SKU0002", sell_through=0.60004),
    ),
    regional_budget_caps={Region.NORTH: 120_000.0},
    kvi_price_tolerance=0.05,
    max_promoted_skus_per_category_per_region=4,
)


def matched(labels: RequestLabels, request: PlanningRequest | None = REQUEST) -> dict[str, bool]:
    return {match.field: match.matched for match in match_fields(labels, request)}


# ---------------------------------------------------------------- field matching rules


def test_only_labelled_fields_are_scored_in_field_order() -> None:
    labels = RequestLabels(marketing_budget=200_000, regions=(Region.WEST, Region.NORTH))

    assert [match.field for match in match_fields(labels, REQUEST)] == [
        "regions",
        "marketing_budget",
    ]
    assert match_fields(RequestLabels(), REQUEST) == ()


def test_sets_match_in_any_order_and_only_when_equal() -> None:
    assert matched(
        RequestLabels(
            regions=(Region.WEST, Region.NORTH, Region.WEST),
            categories=("Beverages", "Snacks"),
            sku_ids=(),
        )
    ) == {"regions": True, "categories": True, "sku_ids": True}
    assert matched(
        RequestLabels(regions=(Region.NORTH,), categories=("Snacks", "Beverages", "Dairy"))
    ) == {"regions": False, "categories": False}


def test_money_matches_within_a_rupee() -> None:
    assert matched(RequestLabels(marketing_budget=200_000)) == {"marketing_budget": True}
    assert matched(RequestLabels(marketing_budget=200_001.5)) == {"marketing_budget": False}
    assert matched(RequestLabels(regional_budget_caps={Region.NORTH: 120_000.9})) == {
        "regional_budget_caps": True
    }
    assert matched(
        RequestLabels(regional_budget_caps={Region.NORTH: 120_000, Region.WEST: 50_000})
    ) == {"regional_budget_caps": False}


def test_fractions_match_within_a_hundredth_of_a_point() -> None:
    assert matched(RequestLabels(min_margin=0.18009, kvi_price_tolerance=0.05)) == {
        "min_margin": True,
        "kvi_price_tolerance": True,
    }
    assert matched(RequestLabels(min_margin=0.181, kvi_price_tolerance=0.06)) == {
        "min_margin": False,
        "kvi_price_tolerance": False,
    }


def test_windows_and_the_promoted_sku_cap_match_exactly() -> None:
    assert matched(
        RequestLabels(
            promo_window=PromoWindow(start_week=108, end_week=109),
            max_promoted_skus_per_category_per_region=4,
        )
    ) == {"promo_window": True, "max_promoted_skus_per_category_per_region": True}
    assert matched(
        RequestLabels(
            promo_window=PromoWindow(start_week=107, end_week=109),
            max_promoted_skus_per_category_per_region=5,
        )
    ) == {"promo_window": False, "max_promoted_skus_per_category_per_region": False}


def test_clearance_targets_match_as_a_set_with_each_sell_through_within_tolerance() -> None:
    same = (
        ClearanceTarget(sku_id="SKU0002", sell_through=0.6),
        ClearanceTarget(sku_id="SKU0006", sell_through=0.6),
    )
    one_missing = same[:1]
    one_off = (same[0], ClearanceTarget(sku_id="SKU0006", sell_through=0.5))

    assert matched(RequestLabels(clearance_targets=same)) == {"clearance_targets": True}
    assert matched(RequestLabels(clearance_targets=one_missing)) == {"clearance_targets": False}
    assert matched(RequestLabels(clearance_targets=one_off)) == {"clearance_targets": False}


def test_an_unset_optional_field_does_not_match_a_labelled_value() -> None:
    bare = REQUEST.model_copy(update={"min_margin": None, "kvi_price_tolerance": None})

    assert matched(RequestLabels(min_margin=0.18, kvi_price_tolerance=0.05), bare) == {
        "min_margin": False,
        "kvi_price_tolerance": False,
    }


def test_with_no_request_every_labelled_field_is_wrong() -> None:
    matches = match_fields(RequestLabels(marketing_budget=200_000, min_margin=0.18), None)

    assert [(m.field, m.got, m.matched) for m in matches] == [
        ("marketing_budget", None, False),
        ("min_margin", None, False),
    ]


def test_a_match_shows_the_label_and_what_was_read() -> None:
    [budget] = match_fields(RequestLabels(marketing_budget=150_000), REQUEST)

    assert (budget.expected, budget.got) == ("150000", "200000.4")


def relaxed(kind: ConstraintKind, current: float, to: float | None, **where: object) -> Relaxation:
    change = RelaxedConstraint.model_validate(
        {"kind": kind, "current": current, "relaxed": to, "change": 0.01, **where}
    )
    return Relaxation(changes=(change,), policy_binds=False, proven=True)


def test_an_accepted_relaxation_is_applied_to_the_labels_before_they_are_matched() -> None:
    # The labels are what the scenario states; the request read after accepting a relaxation
    # holds the relaxation's values, which the optimiser computes (ADR 0076).
    labels = RequestLabels(
        marketing_budget=150_000,
        min_margin=0.2,
        clearance_targets=(
            ClearanceTarget(sku_id="SKU0002", sell_through=0.6),
            ClearanceTarget(sku_id="SKU0006", sell_through=0.7),
            ClearanceTarget(sku_id="SKU0009", sell_through=0.9),
        ),
        regional_budget_caps={Region.NORTH: 100_000.0},
        kvi_price_tolerance=0.03,
        max_promoted_skus_per_category_per_region=3,
    )
    accepted = (
        relaxed(ConstraintKind.MARKETING_BUDGET, 150_000, 200_000.4),
        relaxed(ConstraintKind.MINIMUM_MARGIN, 0.2, 0.18),
        relaxed(ConstraintKind.CLEARANCE_TARGET, 0.7, 0.6, sku_id="SKU0006"),
        relaxed(ConstraintKind.CLEARANCE_TARGET, 0.9, None, sku_id="SKU0009"),
        relaxed(ConstraintKind.REGIONAL_BUDGET, 100_000, 120_000, region=Region.NORTH),
        relaxed(ConstraintKind.KVI_PRICE_TOLERANCE, 0.03, 0.05),
        relaxed(ConstraintKind.MAX_PROMOTED_SKUS, 3, 4),
    )

    before = match_fields(labels, REQUEST)
    after = match_fields(labels, REQUEST, accepted=accepted)

    assert not any(match.matched for match in before)
    assert [(match.field, match.matched) for match in after] == [
        ("marketing_budget", True),
        ("min_margin", True),
        ("clearance_targets", True),
        ("regional_budget_caps", True),
        ("kvi_price_tolerance", True),
        ("max_promoted_skus_per_category_per_region", True),
    ]
    [budget, *_] = after
    assert budget.expected == "200000.4"


def test_an_accepted_relaxation_never_scores_a_field_the_scenario_does_not_label() -> None:
    accepted = (relaxed(ConstraintKind.MARKETING_BUDGET, 150_000, 200_000.4),)

    assert match_fields(RequestLabels(min_margin=0.18), REQUEST, accepted=accepted) == (
        match_fields(RequestLabels(min_margin=0.18), REQUEST)
    )


def test_a_kvi_tolerance_the_relaxation_turns_off_is_expected_off() -> None:
    accepted = (relaxed(ConstraintKind.KVI_PRICE_TOLERANCE, 0.03, None),)
    off = REQUEST.model_copy(update={"kvi_price_tolerance": None})
    labels = RequestLabels(kvi_price_tolerance=0.03)

    assert [(m.field, m.matched) for m in match_fields(labels, off, accepted=accepted)] == [
        ("kvi_price_tolerance", True)
    ]
    assert [(m.field, m.matched) for m in match_fields(labels, REQUEST, accepted=accepted)] == [
        ("kvi_price_tolerance", False)
    ]


# ---------------------------------------------------------------- extraction accuracy


def run(**fields: object) -> RunResult:
    return RunResult.model_validate({"run": 1, "outcome": RunOutcome.PLANNED, **fields})


def field(name: str, ok: bool) -> FieldMatch:
    return FieldMatch(field=name, expected="x", got="x" if ok else "y", matched=ok)


def test_extraction_accuracy_is_correct_fields_over_labelled_fields_across_runs() -> None:
    runs = [
        run(
            extraction=(
                field("regions", True),
                field("categories", True),
                field("marketing_budget", False),
                field("promo_window", True),
            )
        ),
        run(
            outcome=RunOutcome.FAILED,
            extraction=(field("marketing_budget", False), field("regions", False)),
        ),
        run(),
    ]

    metric = extraction_accuracy(runs)

    assert (metric.name, metric.count, metric.of, metric.value) == (
        "extraction_accuracy",
        3,
        6,
        0.5,
    )
    assert (metric.target, metric.direction, metric.passed) == (0.95, "at_least", False)
    assert metric.breakdown == {"marketing_budget": 2, "regions": 1}
    assert extraction_accuracy([run()]).passed is None


def test_extraction_accuracy_passes_at_95_percent() -> None:
    runs = [run(extraction=tuple(field(f"f{i}", i != 0) for i in range(20)))]

    assert extraction_accuracy(runs).passed is True


# ---------------------------------------------------------------- clarification behaviour


def scenario(group: str = "vague_or_conflicting", **fields: object) -> Scenario:
    expect = fields.pop("expect", [{"asks_clarification": "marketing_budget"}])
    return Scenario.model_validate(
        {
            "name": "s",
            "group": group,
            "brief": "b",
            "as_of_week": 104,
            "seed": 0,
            "expect": expect,
            **fields,
        }
    )


VAGUE = scenario(
    expect=[
        {"asks_clarification": "marketing_budget"},
        {"asks_clarification": "clearance_targets"},
        {"flags_assumption": "min_margin"},
    ]
)


def test_a_vague_scenario_passes_when_it_asks_or_flags_a_field_it_names() -> None:
    asked = check_clarification(VAGUE, asked=("promo_window", "marketing_budget"), flagged=())
    per_sku = check_clarification(VAGUE, asked=("clearance_targets.0",), flagged=())
    flagged = check_clarification(VAGUE, asked=(), flagged=("min_margin", "objective"))
    neither = check_clarification(VAGUE, asked=("promo_window",), flagged=("objective",))

    assert asked == ClarificationCheck(
        named=("marketing_budget", "clearance_targets", "min_margin"),
        asked=("marketing_budget",),
        flagged=(),
        passed=True,
    )
    assert per_sku is not None
    assert per_sku.asked == ("clearance_targets.0",)
    assert per_sku.passed
    assert flagged is not None
    assert (flagged.flagged, flagged.passed) == (("min_margin",), True)
    assert neither is not None
    assert not neither.passed


def test_clarification_is_checked_only_for_vague_or_conflicting_scenarios() -> None:
    assert check_clarification(scenario("standard_festive"), asked=("x",), flagged=()) is None


def test_an_ask_other_scenarios_do_not_expect_is_unneeded() -> None:
    festive = scenario("standard_festive", expect=[{"asks_clarification": "promo_window"}])

    assert unneeded_asks(festive, ("promo_window", "marketing_budget")) == ("marketing_budget",)
    assert unneeded_asks(festive, ("promo_window",)) == ()
    assert unneeded_asks(VAGUE, ("anything",)) == ()


def clarified(asked: bool, flagged: bool) -> ClarificationCheck:
    return ClarificationCheck(
        named=("marketing_budget",),
        asked=("marketing_budget",) if asked else (),
        flagged=("marketing_budget",) if flagged else (),
        passed=asked or flagged,
    )


def test_clarification_behaviour_is_the_share_of_vague_runs_that_ask_or_flag() -> None:
    runs = [
        run(clarification=clarified(asked=True, flagged=False)),
        run(clarification=clarified(asked=True, flagged=True)),
        run(clarification=clarified(asked=False, flagged=True)),
        run(clarification=clarified(asked=False, flagged=False)),
        run(unneeded_asks=("promo_window",)),
        run(),
    ]

    metric = clarification_behaviour(runs)

    assert (metric.name, metric.count, metric.of, metric.value) == (
        "clarification_behaviour",
        3,
        4,
        0.75,
    )
    assert (metric.target, metric.passed) == (1.0, False)
    assert metric.breakdown == {"asked": 2, "flagged_only": 1, "neither": 1, "unneeded_asks": 1}


def test_a_vague_scenario_must_name_a_field_to_ask_or_flag() -> None:
    with pytest.raises(ValueError, match="asks_clarification or flags_assumption"):
        scenario(expect=[{"declares_infeasible": False}])


# ---------------------------------------------------------------- infeasibility handling


def infeasible(
    status: SolveStatus = SolveStatus.INFEASIBLE,
    relaxed: bool = True,
    binding: bool = True,
) -> PlanRevision:
    return PlanRevision(
        number=1,
        solver_status=status,
        binding_constraints=(
            BindingConstraint(
                kind=ConstraintKind.CLEARANCE_TARGET,
                source=ConstraintSource.BRIEF,
                limit=0.9,
                region=Region.NORTH,
                sku_id="SKU0029",
                evidence=BindingEvidence.INFEASIBLE,
                objective_gain=None,
            ),
        )
        if binding
        else (),
        relaxation=Relaxation(
            changes=(
                RelaxedConstraint(
                    kind=ConstraintKind.CLEARANCE_TARGET,
                    sku_id="SKU0029",
                    current=0.9,
                    relaxed=0.7027,
                    change=0.219,
                ),
            ),
            policy_binds=True,
            proven=status is SolveStatus.INFEASIBLE,
        )
        if relaxed
        else None,
    )


INFEASIBLE_GROUP = scenario("infeasible_constraints", expect=[])


def test_an_infeasible_scenario_passes_when_declared_with_a_relaxation_and_what_binds() -> None:
    check = check_infeasibility(INFEASIBLE_GROUP, infeasible())

    assert check == InfeasibilityCheck(
        revision=1, declared=True, relaxation=True, binding_named=True, passed=True
    )


@pytest.mark.parametrize(
    "revision",
    [
        infeasible(status=SolveStatus.FEASIBLE),
        infeasible(relaxed=False),
        infeasible(binding=False),
        None,
    ],
    ids=["timeout", "no-relaxation", "nothing-binds", "no-plan"],
)
def test_an_infeasible_scenario_fails_without_all_three(revision: PlanRevision | None) -> None:
    check = check_infeasibility(INFEASIBLE_GROUP, revision)

    assert check is not None
    assert not check.passed


def test_infeasibility_is_checked_only_for_infeasible_constraint_scenarios() -> None:
    assert check_infeasibility(scenario("tight_budget", expect=[]), infeasible()) is None


def test_infeasibility_handling_is_the_share_of_infeasible_runs_that_pass() -> None:
    passed = check_infeasibility(INFEASIBLE_GROUP, infeasible())
    timeout = check_infeasibility(INFEASIBLE_GROUP, infeasible(status=SolveStatus.FEASIBLE))
    no_plan = check_infeasibility(INFEASIBLE_GROUP, None)
    runs = [
        run(infeasibility=passed),
        run(infeasibility=timeout),
        run(infeasibility=no_plan),
        run(),
    ]

    metric = infeasibility_handling(runs)

    assert (metric.name, metric.count, metric.of) == ("infeasibility_handling", 1, 3)
    assert (metric.target, metric.passed) == (1.0, False)
    assert metric.breakdown == {
        "not_declared": 1,
        "no_relaxation": 0,
        "nothing_binds": 0,
        "no_plan": 1,
    }


# ---------------------------------------------------------------- grounding


def explained(source: ExplanationSource, reason: FallbackReason | None = None) -> PlanExplanation:
    return PlanExplanation(summary="s", source=source, fallback_reason=reason)


def test_an_explainer_run_records_its_source_and_fallback_reason() -> None:
    assert explainer_run(2, explained(ExplanationSource.LLM)) == ExplainerRun(
        revision=2, source=ExplanationSource.LLM, fallback_reason=None
    )


def test_grounding_scores_every_explainer_run_the_llm_answered() -> None:
    llm = explainer_run(1, explained(ExplanationSource.LLM))
    ungrounded = explainer_run(2, explained(ExplanationSource.TEMPLATE, FallbackReason.UNGROUNDED))
    invalid = explainer_run(1, explained(ExplanationSource.TEMPLATE, FallbackReason.INVALID_ANSWER))
    down = explainer_run(1, explained(ExplanationSource.TEMPLATE, FallbackReason.LLM_UNAVAILABLE))
    runs = [
        run(explanations=(llm, ungrounded)),
        run(explanations=(llm, llm, invalid)),
        run(explanations=(down,)),
    ]

    metric = grounding(runs)

    assert (metric.name, metric.count, metric.of, metric.value) == ("grounding", 3, 5, 0.6)
    assert (metric.target, metric.direction, metric.passed) == (0.98, "at_least", False)
    assert metric.breakdown == {
        "llm": 3,
        "ungrounded": 1,
        "invalid_answer": 1,
        "llm_unavailable": 1,
    }
    assert grounding([run(explanations=(down,))]).value is None


# ---------------------------------------------------------------- latency and cost


def event(n: int, payload: TokensUsed | NodeStarted) -> TraceEvent:
    return TraceEvent(
        id=n, session_id=uuid4(), at=datetime(2026, 9, 28, tzinfo=UTC), node="x", payload=payload
    )


def test_a_sessions_usage_is_the_sum_of_its_token_usage_events() -> None:
    events = [
        event(1, NodeStarted()),
        event(
            2,
            TokensUsed(model="m", input_tokens=100, output_tokens=10, cost_usd=0.01, cost_inr=0.85),
        ),
        event(
            3,
            TokensUsed(model="m", input_tokens=200, output_tokens=20, cost_usd=0.02, cost_inr=1.7),
        ),
        event(
            4,
            TokensUsed(model="free", input_tokens=5, output_tokens=1, cost_usd=None, cost_inr=None),
        ),
    ]

    usage = session_usage(events)

    assert (usage.calls, usage.input_tokens, usage.output_tokens) == (3, 305, 31)
    assert usage.cost_usd == pytest.approx(0.03)
    assert usage.cost_inr == pytest.approx(2.55)
    assert usage.unpriced_models == ("free",)
    assert session_usage([]) == SessionUsage()


def test_latency_is_the_median_session_time_of_the_runs_that_did_not_fail() -> None:
    runs = [
        run(session_s=1.0, llm_s=0.5),
        run(session_s=3.0, llm_s=2.0),
        run(session_s=2.0, llm_s=1.5),
        run(session_s=10.0, llm_s=6.0),
        run(outcome=RunOutcome.FAILED, session_s=99.0, llm_s=90.0),
    ]

    metric = session_latency(runs)

    assert (metric.name, metric.unit, metric.value, metric.count, metric.of) == (
        "session_latency_p50",
        "seconds",
        2.5,
        4,
        5,
    )
    assert (metric.target, metric.passed) == (None, None)
    # The median time waiting on the LLM, whole seconds: the rest is PromoPilot's own work.
    assert metric.breakdown == {"max_s": 10, "llm_p50_s": 2}
    assert session_latency([run(outcome=RunOutcome.FAILED)]).value is None


def test_cost_is_the_median_session_cost_in_rupees_with_the_tokens_it_used() -> None:
    def used(inr: float, calls: int = 2) -> SessionUsage:
        return SessionUsage(
            calls=calls, input_tokens=100, output_tokens=10, cost_usd=inr / 85, cost_inr=inr
        )

    runs = [
        run(usage=used(4.0)),
        run(usage=used(10.0)),
        run(usage=used(6.0)),
        run(outcome=RunOutcome.FAILED, usage=used(50.0)),
        run(usage=SessionUsage(calls=1, unpriced_models=("free",))),
    ]

    metric = session_cost(runs)

    assert (metric.name, metric.unit, metric.value, metric.count, metric.of) == (
        "session_cost_p50",
        "rupees",
        5.0,
        4,
        5,
    )
    assert (metric.target, metric.passed) == (None, None)
    assert metric.breakdown == {
        "calls": 7,
        "input_tokens": 300,
        "output_tokens": 30,
        "unpriced_runs": 1,
    }


# ---------------------------------------------------------------- the new expected properties


def test_relaxation_touches_holds_when_the_final_relaxation_changes_that_kind() -> None:
    touches = RelaxationTouches(relaxation_touches=ConstraintKind.CLEARANCE_TARGET)
    budget = RelaxationTouches(relaxation_touches=ConstraintKind.MARKETING_BUDGET)

    held = check_property(touches, asked=(), revision=infeasible())
    missed = check_property(budget, asked=(), revision=infeasible())

    assert (held.property, held.passed) == ("relaxation_touches: clearance_target", True)
    assert not missed.passed
    assert "clearance_target" in missed.detail
    assert not check_property(budget, asked=(), revision=infeasible(relaxed=False)).passed
    assert not check_property(budget, asked=(), revision=None).passed


def test_flags_assumption_holds_when_the_final_reading_flags_that_field() -> None:
    prop = FlagsAssumption(flags_assumption="min_margin")

    held = check_property(prop, asked=(), revision=None, flagged=("objective", "min_margin"))
    missed = check_property(prop, asked=(), revision=None, flagged=("objective",))

    assert (held.property, held.passed) == ("flags_assumption: min_margin", True)
    assert not missed.passed
    assert "objective" in missed.detail


def test_diff_changes_holds_when_the_final_revisions_diff_lists_that_request_field() -> None:
    prop = DiffChanges(diff_changes="scope.regions")
    amended = PlanRevision(
        number=2,
        solver_status=SolveStatus.OPTIMAL,
        diff=RevisionDiff(
            from_revision=1,
            request_changes=(
                RequestChange(field="scope.regions", before="North, West", after="North"),
            ),
        ),
    )

    held = check_property(prop, asked=(), revision=amended)
    first = check_property(prop, asked=(), revision=infeasible())

    assert (held.property, held.passed) == ("diff_changes: scope.regions", True)
    assert not first.passed
    assert first.detail == "revision 1 has no diff"


def test_kvi_response_present_holds_when_the_notes_and_summary_carry_the_response() -> None:
    prop = KviResponsePresent(kvi_response_present=True)
    response = ("Competitor is 5.1% cheaper on K2 (Rice) in North.", "Matching on 1 SKU.")
    summary = "Plan summary. " + " ".join(response)

    held = check_property(
        prop, asked=(), revision=infeasible(), notes=response, summary=summary, kvi=response
    )
    not_in_summary = check_property(
        prop, asked=(), revision=infeasible(), notes=response, summary="Plan.", kvi=response
    )
    no_undercut = check_property(
        prop, asked=(), revision=infeasible(), notes=(), summary="Plan.", kvi=()
    )

    assert (held.property, held.passed) == ("kvi_response_present: true", True)
    assert not not_in_summary.passed
    assert not no_undercut.passed
    assert no_undercut.detail == "no KVI in scope is undercut"
