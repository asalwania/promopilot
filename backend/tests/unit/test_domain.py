import pytest
from pydantic import TypeAdapter, ValidationError

from promopilot.domain import (
    ClearanceTarget,
    CompanyPolicy,
    CompetitorReaction,
    ExplanationSource,
    FallbackReason,
    LineCrossEffect,
    Mechanism,
    OpenIssue,
    PlanExplanation,
    PlanLine,
    PlanningRequest,
    PlanRevision,
    PlanRevisionLine,
    PlanSimulation,
    PromoPlan,
    PromoWindow,
    Region,
    RiskCode,
    RiskFinding,
    Scope,
    Segment,
    SegmentUplift,
    TargetSegment,
    Violation,
    ViolationCode,
    uplift_pct,
)


def line(
    sku_id: str = "SKU001",
    region: Region = Region.NORTH,
    mechanism: Mechanism = Mechanism.PCT_OFF,
    depth_pct: int = 20,
    bundle_partner_sku_id: str | None = None,
) -> PlanLine:
    return PlanLine(
        sku_id=sku_id,
        region=region,
        mechanism=mechanism,
        depth_pct=depth_pct,
        duration_weeks=2,
        start_week=105,
        target_segment=TargetSegment.ALL_CUSTOMERS,
        bundle_partner_sku_id=bundle_partner_sku_id,
    )


def test_promo_plan_rejects_two_plan_lines_for_the_same_sku_in_the_same_region() -> None:
    with pytest.raises(ValidationError, match="one plan line per SKU per region"):
        PromoPlan(lines=(line(depth_pct=20), line(depth_pct=30)))


def test_promo_plan_allows_the_same_sku_in_different_regions() -> None:
    plan = PromoPlan(lines=(line(region=Region.NORTH), line(region=Region.WEST, depth_pct=30)))

    assert len(plan.lines) == 2


def test_bundle_plan_line_requires_a_partner_sku() -> None:
    with pytest.raises(ValidationError, match="BUNDLE needs a bundle partner"):
        line(mechanism=Mechanism.BUNDLE)


def test_only_a_bundle_plan_line_may_name_a_partner_sku() -> None:
    with pytest.raises(ValidationError, match="only a BUNDLE"):
        line(mechanism=Mechanism.PCT_OFF, bundle_partner_sku_id="SKU002")


def test_bundle_partner_cannot_be_its_own_anchor() -> None:
    with pytest.raises(ValidationError, match="its own partner"):
        line(mechanism=Mechanism.BUNDLE, bundle_partner_sku_id="SKU001")


def test_bogo_plan_line_is_always_fifty_percent_deep() -> None:
    with pytest.raises(ValidationError, match="BOGO"):
        line(mechanism=Mechanism.BOGO, depth_pct=30)


def test_bundle_partner_cannot_have_its_own_plan_line_in_the_same_region() -> None:
    bundle = line(sku_id="SKU001", mechanism=Mechanism.BUNDLE, bundle_partner_sku_id="SKU002")

    with pytest.raises(ValidationError, match="one plan line per SKU per region"):
        PromoPlan(lines=(bundle, line(sku_id="SKU002")))


def test_bundle_partner_may_have_its_own_plan_line_in_another_region() -> None:
    bundle = line(sku_id="SKU001", mechanism=Mechanism.BUNDLE, bundle_partner_sku_id="SKU002")

    plan = PromoPlan(lines=(bundle, line(sku_id="SKU002", region=Region.SOUTH)))

    assert len(plan.lines) == 2


def test_company_policy_defaults_are_the_adr_0007_table() -> None:
    policy = CompanyPolicy()

    assert policy.margin_floor == 0.15
    assert policy.max_discount_pct == 50
    assert policy.undercut_threshold == 0.05
    assert policy.kvi_price_tolerance == 0.02
    assert policy.kvi_price_tolerance_enabled is False
    assert policy.overstock_threshold_weeks == 8
    assert policy.write_off_rate == 0.30
    assert policy.fixed_cost_per_line_week == {
        Mechanism.PCT_OFF: 500.0,
        Mechanism.FIXED_PRICE: 500.0,
        Mechanism.BOGO: 750.0,
        Mechanism.BUNDLE: 1000.0,
    }
    assert policy.max_promoted_skus_per_category_per_region == 10


def test_company_policy_is_immutable() -> None:
    policy = CompanyPolicy()

    with pytest.raises(ValidationError):
        policy.margin_floor = 0.10  # type: ignore[misc]


def planning_request(**changes: object) -> PlanningRequest:
    fields: dict[str, object] = {
        "as_of_week": 104,
        "scope": Scope(regions=(Region.NORTH, Region.WEST), categories=("Snacks",)),
        "promo_window": PromoWindow(start_week=108, end_week=109),
        "marketing_budget": 200_000.0,
    }
    return PlanningRequest.model_validate(fields | changes)


def test_a_planning_request_sets_no_optional_constraint_by_default() -> None:
    request = planning_request()

    assert request.clearance_targets == ()
    assert request.regional_budget_caps == {}
    assert request.kvi_price_tolerance is None
    assert request.max_promoted_skus_per_category_per_region is None


def test_a_planning_request_carries_the_briefs_optional_constraints() -> None:
    request = planning_request(
        clearance_targets=[{"sku_id": "SKU0001", "sell_through": 0.6}],
        regional_budget_caps={"North": 120_000.0},
        kvi_price_tolerance=0.01,
        max_promoted_skus_per_category_per_region=6,
    )

    assert request.clearance_targets == (ClearanceTarget(sku_id="SKU0001", sell_through=0.6),)
    assert request.regional_budget_caps == {Region.NORTH: 120_000.0}
    assert request.kvi_price_tolerance == 0.01
    assert request.max_promoted_skus_per_category_per_region == 6


@pytest.mark.parametrize("sell_through", [0.0, -0.1, 1.01])
def test_a_clearance_target_is_a_sell_through_above_zero_up_to_one(sell_through: float) -> None:
    with pytest.raises(ValidationError):
        ClearanceTarget(sku_id="SKU0001", sell_through=sell_through)


def test_a_sku_has_at_most_one_clearance_target() -> None:
    target = {"sku_id": "SKU0001", "sell_through": 0.5}
    with pytest.raises(ValidationError, match="one clearance target"):
        planning_request(clearance_targets=[target, target])


def test_a_regional_budget_cap_is_positive_and_for_a_region_in_scope() -> None:
    with pytest.raises(ValidationError, match="not in the scope"):
        planning_request(regional_budget_caps={"South": 50_000.0})
    with pytest.raises(ValidationError):
        planning_request(regional_budget_caps={"North": 0.0})


@pytest.mark.parametrize("probability", [0.0, 0.3, 1.0])
def test_a_competitor_reaction_is_a_match_probability_from_zero_to_one(probability: float) -> None:
    assert CompetitorReaction(match_probability=probability).match_probability == probability


@pytest.mark.parametrize("probability", [-0.1, 1.01])
def test_a_competitor_reaction_rejects_a_probability_outside_zero_to_one(
    probability: float,
) -> None:
    with pytest.raises(ValidationError):
        CompetitorReaction(match_probability=probability)


def test_a_competitor_reaction_takes_no_other_field() -> None:
    with pytest.raises(ValidationError):
        CompetitorReaction.model_validate({"match_probability": 0.5, "match_share": 0.5})


def test_a_stored_simulation_from_before_the_scenario_reads_back_without_one() -> None:
    outcomes = {
        metric: {"p10": 0.0, "p50": 0.0, "p90": 0.0}
        for metric in ("units", "revenue", "gross_profit", "margin", "promo_spend")
    }
    stored = {"n_runs": 100, "seed": 0, "total": outcomes | {"sell_through": None}}

    assert PlanSimulation.model_validate(stored).competitor_reaction is None


def test_a_plan_revision_explanation_has_one_rationale_per_plan_line() -> None:
    planned = PlanRevisionLine(
        line=line(), expected_units=10.0, promo_cost=100.0, expected_incremental_profit=50.0
    )
    explanation = PlanExplanation(
        summary="One line.", rationales=("Why.",), source=ExplanationSource.LLM
    )

    revision = PlanRevision(number=1, lines=(planned,), explanation=explanation)

    assert revision.explanation == explanation
    with pytest.raises(ValidationError, match="one rationale per plan line"):
        PlanRevision(
            number=1,
            lines=(planned,),
            explanation=explanation.model_copy(update={"rationales": ()}),
        )


def test_only_a_template_explanation_records_why_the_llm_was_not_used() -> None:
    fallback = PlanExplanation(
        summary="Template.",
        source=ExplanationSource.TEMPLATE,
        fallback_reason=FallbackReason.UNGROUNDED,
    )

    assert fallback.fallback_reason is FallbackReason.UNGROUNDED
    with pytest.raises(ValidationError, match="only a template explanation"):
        PlanExplanation(
            summary="LLM.",
            source=ExplanationSource.LLM,
            fallback_reason=FallbackReason.LLM_UNAVAILABLE,
        )


def test_an_open_issue_stored_before_risk_findings_still_reads_as_a_violation() -> None:
    # Rows written before #48 have no `kind` (ADR 0051).
    issues = TypeAdapter(tuple[OpenIssue, ...])

    [violation, risk] = issues.validate_python(
        [
            {"code": "BUDGET", "message": "over", "actual": 2.0, "limit": 1.0},
            {
                "kind": "risk",
                "code": "STOCKOUT_RISK",
                "message": "runs out",
                "feedback": "promote it less deeply",
                "actual": 0.3,
                "limit": 0.2,
            },
        ]
    )

    assert violation == Violation(code=ViolationCode.BUDGET, message="over", actual=2.0, limit=1.0)
    assert isinstance(risk, RiskFinding)
    assert risk.code is RiskCode.STOCKOUT_RISK
    assert issues.dump_python((violation,), mode="json")[0]["kind"] == "violation"


def test_uplift_is_the_units_above_baseline_as_a_percentage_of_it() -> None:
    assert uplift_pct(150.0, 100.0) == pytest.approx(50.0)
    assert uplift_pct(80.0, 100.0) == pytest.approx(-20.0)


def test_there_is_no_uplift_without_a_baseline() -> None:
    assert uplift_pct(12.0, 0.0) is None


def test_a_segments_uplift_is_computed_from_its_units_and_baseline() -> None:
    segment = SegmentUplift.of(Segment.FAMILIES, units=300.0, baseline_units=200.0)

    assert segment == SegmentUplift(
        segment=Segment.FAMILIES, units=300.0, baseline_units=200.0, uplift_pct=50.0
    )


def test_a_plan_line_planned_before_uplift_was_kept_reads_back_without_it() -> None:
    planned = PlanRevisionLine(
        line=line(), expected_units=10.0, promo_cost=5.0, expected_incremental_profit=1.0
    )

    assert planned.baseline_units is None
    assert planned.uplift_pct is None
    assert planned.segments == ()
    assert planned.cross_effects == ()


def test_a_plan_line_names_each_segment_once() -> None:
    families = SegmentUplift.of(Segment.FAMILIES, units=3.0, baseline_units=2.0)

    with pytest.raises(ValidationError, match="each segment once"):
        PlanRevisionLine(
            line=line(),
            expected_units=6.0,
            promo_cost=5.0,
            expected_incremental_profit=1.0,
            segments=(families, families),
        )


def test_a_plan_lines_cross_effect_names_the_sku_it_moves() -> None:
    effect = LineCrossEffect(sku_id="SKU002", units_change_pct=-12.5, profit_change=-3000.0)
    planned = PlanRevisionLine(
        line=line(),
        expected_units=10.0,
        promo_cost=5.0,
        expected_incremental_profit=1.0,
        cross_effects=(effect,),
    )

    assert planned.cross_effects[0].sku_id == "SKU002"
