"""The diff between consecutive plan revisions (AG-05, #50, ADR 0052): plan lines added,
removed and changed by (SKU, region), the objective and promo-cost deltas, and what the
planning request changed, all computed deterministically."""

from hypothesis import given
from hypothesis import strategies as st

from promopilot.domain import (
    ClearanceTarget,
    Mechanism,
    PlanLine,
    PlanningRequest,
    PlanRevision,
    PlanRevisionLine,
    PromoWindow,
    Region,
    RequestChange,
    Scope,
    SolveStatus,
    TargetSegment,
)
from promopilot.guardrails import diff_revisions


def planned(
    sku_id: str,
    region: Region = Region.NORTH,
    *,
    depth: int = 20,
    mechanism: Mechanism = Mechanism.PCT_OFF,
    cost: float = 1_000.0,
    profit: float = 2_000.0,
) -> PlanRevisionLine:
    return PlanRevisionLine(
        line=PlanLine(
            sku_id=sku_id,
            region=region,
            mechanism=mechanism,
            depth_pct=depth,
            duration_weeks=2,
            start_week=54,
            target_segment=TargetSegment.ALL_CUSTOMERS,
        ),
        expected_units=100.0,
        promo_cost=cost,
        expected_incremental_profit=profit,
    )


def revision(number: int, *lines: PlanRevisionLine, objective: float | None = None) -> PlanRevision:
    return PlanRevision(
        number=number, lines=lines, solver_status=SolveStatus.OPTIMAL, objective=objective
    )


REQUEST = PlanningRequest(
    as_of_week=52,
    scope=Scope(regions=(Region.NORTH, Region.WEST), categories=("Snacks",)),
    promo_window=PromoWindow(start_week=54, end_week=55),
    marketing_budget=1_000_000.0,
)


def test_lines_are_matched_by_sku_and_region_into_added_removed_and_changed() -> None:
    kept = planned("SKU0001")
    deeper_before, deeper_after = planned("SKU0002", depth=20), planned("SKU0002", depth=30)
    west = planned("SKU0001", Region.WEST)
    new = planned("SKU0003")
    previous = revision(1, kept, deeper_before, west, objective=6_000.0)
    current = revision(2, new, deeper_after, kept, objective=5_000.0)

    diff = diff_revisions(previous, current)

    assert diff.from_revision == 1
    assert diff.added == (new,)
    assert diff.removed == (west,)
    [change] = diff.changed
    assert (change.sku_id, change.region, change.fields) == (
        "SKU0002",
        Region.NORTH,
        ("depth_pct",),
    )
    assert (change.before, change.after) == (deeper_before, deeper_after)
    assert diff.unchanged == 1


def test_a_line_whose_decision_is_the_same_is_unchanged_even_when_its_numbers_moved() -> None:
    previous = revision(1, planned("SKU0001", cost=1_000.0, profit=2_000.0))
    current = revision(2, planned("SKU0001", cost=1_000.0, profit=1_500.0))

    diff = diff_revisions(previous, current)

    assert (diff.added, diff.removed, diff.changed, diff.unchanged) == ((), (), (), 1)


def test_the_mechanism_and_every_other_decision_field_count_as_changes() -> None:
    before = planned("SKU0001", mechanism=Mechanism.PCT_OFF, depth=20)
    after = planned("SKU0001", mechanism=Mechanism.BOGO, depth=50)

    [change] = diff_revisions(revision(1, before), revision(2, after)).changed

    assert change.fields == ("mechanism", "depth_pct")


def test_the_objective_and_promo_cost_deltas() -> None:
    previous = revision(
        1, planned("SKU0001", cost=1_000.0), planned("SKU0002", cost=500.0), objective=6_000.0
    )
    current = revision(2, planned("SKU0001", cost=700.0), objective=4_500.0)

    diff = diff_revisions(previous, current)

    assert (diff.objective_before, diff.objective_after, diff.objective_delta) == (
        6_000.0,
        4_500.0,
        -1_500.0,
    )
    assert (diff.promo_cost_before, diff.promo_cost_after, diff.promo_cost_delta) == (
        1_500.0,
        700.0,
        -800.0,
    )


def test_without_an_objective_on_either_side_there_is_no_objective_delta() -> None:
    diff = diff_revisions(revision(1), revision(2, objective=10.0))

    assert (diff.objective_before, diff.objective_after, diff.objective_delta) == (
        None,
        10.0,
        None,
    )


def test_request_changes_are_each_changed_field_shown_before_and_after() -> None:
    amended = REQUEST.model_copy(
        update={
            "scope": Scope(regions=(Region.NORTH,), categories=("Snacks",)),
            "marketing_budget": 600_000.0,
            "min_margin": 0.2,
            "clearance_targets": (ClearanceTarget(sku_id="SKU0029", sell_through=0.7027),),
        }
    )

    diff = diff_revisions(revision(1), revision(2), previous_request=REQUEST, request=amended)

    assert diff.request_changes == (
        RequestChange(field="scope.regions", before="North, West", after="North"),
        RequestChange(field="marketing_budget", before="₹10 lakh", after="₹6 lakh"),
        RequestChange(field="min_margin", before="company policy", after="20%"),
        RequestChange(field="clearance_targets", before="none", after="SKU0029 at 70.3%"),
    )


def test_an_unchanged_request_or_a_missing_one_has_no_request_changes() -> None:
    assert (
        diff_revisions(
            revision(1), revision(2), previous_request=REQUEST, request=REQUEST
        ).request_changes
        == ()
    )
    assert diff_revisions(revision(1), revision(2), request=REQUEST).request_changes == ()


LINES = st.lists(
    st.builds(
        planned,
        st.sampled_from(["SKU0001", "SKU0002", "SKU0003", "SKU0004"]),
        st.sampled_from([Region.NORTH, Region.WEST]),
        depth=st.sampled_from([10, 20, 30]),
    ),
    max_size=8,
    unique_by=lambda planned_line: (planned_line.line.sku_id, planned_line.line.region),
)


@given(LINES, LINES)
def test_every_line_is_accounted_for_exactly_once(
    before: list[PlanRevisionLine], after: list[PlanRevisionLine]
) -> None:
    diff = diff_revisions(revision(1, *before), revision(2, *after))

    assert len(diff.added) + len(diff.changed) + diff.unchanged == len(after)
    assert len(diff.removed) + len(diff.changed) + diff.unchanged == len(before)
    assert diff_revisions(revision(1, *before), revision(2, *before)).changed == ()
