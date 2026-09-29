"""`no_strong_substitutes_together` on hand-built inputs (#56, ADR 0065): which true substitute
pairs are strong, which are in a request's scope, and when a plan promotes two together."""

import pandas as pd
import pytest

from promopilot.datagen.truth import CrossEffect
from promopilot.domain import (
    Mechanism,
    PlanLine,
    PlanRevision,
    PlanRevisionLine,
    Region,
    Scope,
    SolveStatus,
    TargetSegment,
)
from promopilot.evals import NoStrongSubstitutesTogether, SubstitutePair
from promopilot.evals.metrics import check_property
from promopilot.evals.substitutes import (
    STRONG_SUBSTITUTE_THETA,
    promoted_together,
    strong_in_scope,
    strong_substitutes,
)

PROP = NoStrongSubstitutesTogether(no_strong_substitutes_together=True)
PAIR = SubstitutePair(first="A", second="B", theta=0.6)


def effects(*directed: tuple[str, str, float]) -> list[CrossEffect]:
    return [CrossEffect(sku_id=a, other_sku_id=b, theta=theta) for a, b, theta in directed]


def test_a_pair_is_strong_when_its_larger_directed_theta_reaches_the_threshold() -> None:
    pairs = [("A", "B"), ("C", "D"), ("E", "F")]
    thetas = effects(
        ("A", "B", 0.35),
        ("B", "A", 0.5),
        ("C", "D", 0.49),
        ("D", "C", 0.3),
        ("E", "F", 0.8),
        ("F", "E", 0.7),
        # A complement pair's effect is never a substitute.
        ("A", "Z", -0.5),
        ("Z", "A", -0.4),
    )

    strong = strong_substitutes(pairs, thetas)

    assert STRONG_SUBSTITUTE_THETA == 0.5
    assert strong == (
        SubstitutePair(first="A", second="B", theta=0.5),
        SubstitutePair(first="E", second="F", theta=0.8),
    )


def test_a_pair_is_in_scope_when_both_skus_are_in_its_categories_and_named_skus() -> None:
    products = pd.DataFrame(
        {
            "sku_id": ["A", "B", "C", "D"],
            "category": ["Snacks", "Snacks", "Snacks", "Dairy"],
        }
    )
    pairs = (
        SubstitutePair(first="A", second="B", theta=0.6),
        SubstitutePair(first="B", second="C", theta=0.7),
        SubstitutePair(first="C", second="D", theta=0.9),
    )
    snacks = Scope(regions=(Region.NORTH,), categories=("Snacks",))
    named = Scope(regions=(Region.NORTH,), categories=("Snacks",), sku_ids=("A", "B"))

    assert strong_in_scope(pairs, products, snacks) == pairs[:2]
    assert strong_in_scope(pairs, products, named) == pairs[:1]


def line(
    sku_id: str,
    *,
    region: Region = Region.NORTH,
    start_week: int = 108,
    duration_weeks: int = 2,
    segment: TargetSegment = TargetSegment.ALL_CUSTOMERS,
    partner: str | None = None,
) -> PlanLine:
    return PlanLine(
        sku_id=sku_id,
        region=region,
        mechanism=Mechanism.PCT_OFF if partner is None else Mechanism.BUNDLE,
        depth_pct=20,
        duration_weeks=duration_weeks,
        start_week=start_week,
        target_segment=segment,
        bundle_partner_sku_id=partner,
    )


@pytest.mark.parametrize(
    ("lines", "regions"),
    [
        ((line("A"), line("B")), (Region.NORTH,)),
        ((line("A"), line("B", start_week=109, duration_weeks=1)), (Region.NORTH,)),
        ((line("A"), line("B", region=Region.WEST)), ()),
        ((line("A", duration_weeks=1), line("B", start_week=109, duration_weeks=1)), ()),
        (
            (
                line("A", segment=TargetSegment.FAMILIES),
                line("B", segment=TargetSegment.PREMIUM),
            ),
            (),
        ),
        (
            (
                line("A", segment=TargetSegment.FAMILIES),
                line("B", segment=TargetSegment.ALL_CUSTOMERS),
            ),
            (Region.NORTH,),
        ),
        ((line("X", partner="B"), line("A")), (Region.NORTH,)),
        ((line("A", partner="B"),), (Region.NORTH,)),
        (
            (line("A"), line("B"), line("A", region=Region.EAST), line("B", region=Region.EAST)),
            (
                Region.NORTH,
                Region.EAST,
            ),
        ),
    ],
    ids=[
        "same-region-and-weeks",
        "one-common-week",
        "other-region",
        "back-to-back-weeks",
        "different-exclusive-segments",
        "all-customers-overlaps-a-segment",
        "a-bundle-partner-is-promoted",
        "bundled-with-each-other",
        "in-two-regions",
    ],
)
def test_two_skus_are_promoted_together_in_a_region_with_a_common_week_and_segment(
    lines: tuple[PlanLine, ...], regions: tuple[Region, ...]
) -> None:
    assert promoted_together(PAIR, lines) == regions


def revision(*lines: PlanLine) -> PlanRevision:
    return PlanRevision(
        number=2,
        solver_status=SolveStatus.OPTIMAL,
        lines=tuple(
            PlanRevisionLine(
                line=planned,
                expected_units=10.0,
                promo_cost=100.0,
                expected_incremental_profit=50.0,
            )
            for planned in lines
        ),
    )


def test_the_property_holds_when_no_strong_pair_in_scope_is_promoted_together() -> None:
    pairs = (PAIR, SubstitutePair(first="C", second="D", theta=0.55))

    kept = check_property(
        PROP, asked=(), revision=revision(line("A"), line("C")), substitutes=pairs
    )
    broken = check_property(
        PROP, asked=(), revision=revision(line("A"), line("B"), line("C")), substitutes=pairs
    )

    assert (kept.property, kept.passed) == ("no_strong_substitutes_together: true", True)
    assert (
        kept.detail == "revision 2 promotes none of the 2 strong substitute pairs in scope together"
    )
    assert not broken.passed
    assert broken.detail == "revision 2 promotes A and B (θ 0.60) together in North"


def test_the_property_fails_with_no_final_revision_or_no_strong_pair_in_scope() -> None:
    none_in_scope = check_property(PROP, asked=(), revision=revision(line("A")), substitutes=())
    no_plan = check_property(PROP, asked=(), revision=None, substitutes=(PAIR,))

    assert not none_in_scope.passed
    assert none_in_scope.detail == "no strong substitute pair in scope, so nothing is tested"
    assert not no_plan.passed
    assert no_plan.detail == "no final plan revision"
