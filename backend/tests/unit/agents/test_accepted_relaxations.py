"""Accepting a relaxation applies its own values to the Context agent's reading, in code
(ADR 0083): a change for one SKU never touches another's target, and a later amendment that
states another value for the field wins."""

import pytest

from promopilot.agents import AcceptedRelaxation, ContextReading, apply_accepted
from promopilot.domain import (
    Assumption,
    AssumptionSource,
    ClearanceTarget,
    CompanyPolicy,
    ConstraintKind,
    PlanningRequest,
    PromoWindow,
    Region,
    Relaxation,
    RelaxedConstraint,
    Scope,
)

POLICY = CompanyPolicy(kvi_price_tolerance_enabled=True)

REQUEST = PlanningRequest(
    as_of_week=104,
    scope=Scope(regions=(Region.NORTH, Region.WEST), categories=("Snacks", "Beverages")),
    promo_window=PromoWindow(start_week=108, end_week=109),
    marketing_budget=6_00_000.0,
    min_margin=0.18,
    clearance_targets=(
        ClearanceTarget(sku_id="SKU0002", sell_through=0.6),
        ClearanceTarget(sku_id="SKU0006", sell_through=0.6),
    ),
    regional_budget_caps={Region.NORTH: 90_000.0},
    kvi_price_tolerance=0.01,
    max_promoted_skus_per_category_per_region=4,
)

ASSUMPTIONS = (
    Assumption(
        field="marketing_budget", value="₹600,000", source=AssumptionSource.BRIEF, confidence=1
    ),
    Assumption(field="min_margin", value="18.0%", source=AssumptionSource.BRIEF, confidence=1),
    Assumption(
        field="clearance_targets",
        value="60.0% sell-through for subcategory Namkeen; pack size 400g: SKU0002, SKU0006",
        source=AssumptionSource.BRIEF,
        confidence=1,
    ),
    Assumption(
        field="regional_budget_caps",
        value="North ₹90,000",
        source=AssumptionSource.BRIEF,
        confidence=1,
    ),
    Assumption(
        field="kvi_price_tolerance", value="1.0%", source=AssumptionSource.BRIEF, confidence=1
    ),
    Assumption(
        field="max_promoted_skus_per_category_per_region",
        value="4",
        source=AssumptionSource.BRIEF,
        confidence=1,
    ),
)

READING = ContextReading(request=REQUEST, assumptions=ASSUMPTIONS, questions=())


def accepted(*changes: RelaxedConstraint, revision: int = 3) -> AcceptedRelaxation:
    return AcceptedRelaxation(
        revision_number=revision,
        relaxation=Relaxation(changes=changes, policy_binds=False, proven=True),
    )


SKU0006 = RelaxedConstraint(
    kind=ConstraintKind.CLEARANCE_TARGET,
    sku_id="SKU0006",
    current=0.6,
    relaxed=0.5986,
    change=0.0023,
)


def targets(reading: ContextReading) -> list[tuple[str, float]]:
    assert reading.request is not None
    return [(t.sku_id, t.sell_through) for t in reading.request.clearance_targets]


def test_a_clearance_relaxation_for_one_sku_leaves_every_other_sku_target_unchanged() -> None:
    applied = apply_accepted(READING, [accepted(SKU0006)], POLICY)

    assert targets(applied) == [("SKU0002", 0.6), ("SKU0006", 0.5986)]
    # The brief's grouped reading stays; the accepted value for SKU0006 follows it.
    assert applied.assumptions[: len(ASSUMPTIONS)] == ASSUMPTIONS
    assert applied.assumptions[len(ASSUMPTIONS) :] == (
        Assumption(
            field="clearance_targets",
            value="59.86% sell-through for SKU0006",
            source=AssumptionSource.BRIEF,
            confidence=1,
            note="The accepted relaxation of plan revision 3: it replaces the 60.00% the "
            "brief asks for SKU0006.",
        ),
    )


def test_nothing_accepted_or_nothing_to_plan_leaves_the_reading_as_it_is() -> None:
    assert apply_accepted(READING, [], POLICY) == READING
    asking = ContextReading(request=None, assumptions=ASSUMPTIONS, questions=())
    assert apply_accepted(asking, [accepted(SKU0006)], POLICY) == asking


def test_a_later_amendment_stating_another_value_for_the_field_wins() -> None:
    # "Clear 50% of the namkeen" after the accept: the reading no longer gives the 60% the
    # relaxation relaxed from, so the manager's newer words stand (ADR 0083 D2).
    restated = READING.request.model_copy(  # type: ignore[union-attr]
        update={
            "clearance_targets": (
                ClearanceTarget(sku_id="SKU0002", sell_through=0.5),
                ClearanceTarget(sku_id="SKU0006", sell_through=0.5),
            )
        }
    )
    reading = ContextReading(request=restated, assumptions=ASSUMPTIONS, questions=())

    applied = apply_accepted(reading, [accepted(SKU0006)], POLICY)

    assert applied == reading


def test_a_dropped_target_is_removed_and_said_so() -> None:
    dropped = SKU0006.model_copy(update={"relaxed": None, "change": 1.0})

    applied = apply_accepted(READING, [accepted(dropped)], POLICY)

    assert targets(applied) == [("SKU0002", 0.6)]
    assert applied.assumptions[-1].value == "none for SKU0006"
    assert applied.assumptions[-1].note == (
        "The accepted relaxation of plan revision 3: it drops the 60.00% the brief asks for "
        "SKU0006."
    )


def test_relaxations_accepted_one_after_another_each_apply() -> None:
    second = SKU0006.model_copy(update={"current": 0.5986, "relaxed": 0.55})

    applied = apply_accepted(READING, [accepted(SKU0006), accepted(second, revision=4)], POLICY)

    assert targets(applied) == [("SKU0002", 0.6), ("SKU0006", 0.55)]
    assert [a.value for a in applied.assumptions[len(ASSUMPTIONS) :]] == [
        "59.86% sell-through for SKU0006",
        "55.00% sell-through for SKU0006",
    ]


def test_every_other_kind_of_change_takes_the_relaxed_value_and_rewrites_its_assumption() -> None:
    relaxation = accepted(
        RelaxedConstraint(
            kind=ConstraintKind.MARKETING_BUDGET,
            current=6_00_000.0,
            relaxed=6_20_344.46,
            change=0.03,
        ),
        RelaxedConstraint(
            kind=ConstraintKind.REGIONAL_BUDGET,
            region=Region.NORTH,
            current=90_000.0,
            relaxed=95_000.5,
            change=0.06,
        ),
        RelaxedConstraint(
            kind=ConstraintKind.MINIMUM_MARGIN, current=0.18, relaxed=0.1725, change=0.04
        ),
        RelaxedConstraint(
            kind=ConstraintKind.MAX_PROMOTED_SKUS, current=4.0, relaxed=6.0, change=0.5
        ),
        RelaxedConstraint(
            kind=ConstraintKind.KVI_PRICE_TOLERANCE, current=0.01, relaxed=0.02, change=1.0
        ),
    )

    applied = apply_accepted(READING, [relaxation], POLICY)

    request = applied.request
    assert request is not None
    assert request.marketing_budget == 6_20_344.46
    assert request.regional_budget_caps == {Region.NORTH: 95_000.5}
    assert request.min_margin == 0.1725
    assert request.max_promoted_skus_per_category_per_region == 6
    assert request.kvi_price_tolerance == 0.02
    assert request.clearance_targets == REQUEST.clearance_targets
    note = "The accepted relaxation of plan revision 3."
    by_field = {a.field: a for a in applied.assumptions}
    assert len(applied.assumptions) == len(ASSUMPTIONS), "rewritten in place, not added"
    assert [(f, by_field[f].value, by_field[f].note) for f in by_field] == [
        ("marketing_budget", "₹620,344.46", note),
        ("min_margin", "17.25%", note),
        (
            "clearance_targets",
            "60.0% sell-through for subcategory Namkeen; pack size 400g: SKU0002, SKU0006",
            None,
        ),
        ("regional_budget_caps", "North ₹95,000.50", note),
        ("kvi_price_tolerance", "2.00%", note),
        ("max_promoted_skus_per_category_per_region", "6", note),
    ]
    assert all(
        a.source is AssumptionSource.BRIEF and a.confidence == 1 for a in applied.assumptions
    )


def test_a_kvi_tolerance_turned_off_reads_off() -> None:
    off = RelaxedConstraint(
        kind=ConstraintKind.KVI_PRICE_TOLERANCE, current=0.01, relaxed=None, change=1.0
    )

    applied = apply_accepted(READING, [accepted(off)], CompanyPolicy())

    assert applied.request is not None
    assert applied.request.kvi_price_tolerance is None
    assert {a.field: a.value for a in applied.assumptions}["kvi_price_tolerance"] == "off"


def test_company_policy_is_never_relaxed() -> None:
    floor = RelaxedConstraint(
        kind=ConstraintKind.MARGIN_FLOOR, current=0.15, relaxed=0.1, change=0.3
    )

    with pytest.raises(ValueError, match="company policy"):
        apply_accepted(READING, [accepted(floor)], POLICY)
