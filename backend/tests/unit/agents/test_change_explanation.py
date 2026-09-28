"""What changed and why (AG-05, #50, ADR 0052): the Explainer writes what changed from the
previous plan revision in the same call as its summary, grounded against the diff and the
planning-request changes, with template sentences as its fallback."""

from hypothesis import given, settings
from hypothesis import strategies as st

from promopilot.agents import (
    ExplainerAnswer,
    LineRationale,
    explain_plan,
    explainer_prompt,
    plan_data,
    template_explanations,
)
from promopilot.domain import (
    ExplanationSource,
    FallbackReason,
    Mechanism,
    PlanLine,
    PlanningRequest,
    PlanRevision,
    PlanRevisionLine,
    PromoWindow,
    Region,
    Scope,
    SolveStatus,
    TargetSegment,
)
from promopilot.guardrails import check_numeric_grounding, diff_revisions
from promopilot.llm import FakeProvider
from tests.unit.agents.test_graph import POLICY

BEFORE = PlanningRequest(
    as_of_week=52,
    scope=Scope(regions=(Region.NORTH, Region.WEST), categories=("Snacks",)),
    promo_window=PromoWindow(start_week=54, end_week=55),
    marketing_budget=10_00_000.0,
)
AFTER = BEFORE.model_copy(update={"marketing_budget": 6_00_000.0})


def line(sku_id: str, region: Region, cost: float, profit: float) -> PlanRevisionLine:
    return PlanRevisionLine(
        line=PlanLine(
            sku_id=sku_id,
            region=region,
            mechanism=Mechanism.PCT_OFF,
            depth_pct=20,
            duration_weeks=2,
            start_week=54,
            target_segment=TargetSegment.ALL_CUSTOMERS,
        ),
        expected_units=4_000.0,
        promo_cost=cost,
        expected_incremental_profit=profit,
    )


FIRST = PlanRevision(
    number=1,
    lines=(
        line("SKU0001", Region.NORTH, 3_00_000.0, 2_50_000.0),
        line("SKU0002", Region.WEST, 4_50_000.0, 1_20_000.0),
    ),
    solver_status=SolveStatus.OPTIMAL,
    objective=3_70_000.0,
)


def amended() -> PlanRevision:
    current = PlanRevision(
        number=2,
        lines=(line("SKU0001", Region.NORTH, 3_00_000.0, 2_50_000.0),),
        solver_status=SolveStatus.OPTIMAL,
        objective=2_50_000.0,
    )
    diff = diff_revisions(FIRST, current, previous_request=BEFORE, request=AFTER)
    return current.model_copy(update={"diff": diff})


RATIONALES = [LineRationale(line=1, rationale="SKU0001 at 20% off in North.")]
GROUNDED = ExplainerAnswer(
    summary="One Snacks line in North.",
    rationales=RATIONALES,
    changes="The marketing budget went from ₹10 lakh to ₹6 lakh, so SKU0002 in West was "
    "dropped and the objective fell from ₹3.7 lakh to ₹2.5 lakh.",
)


async def test_the_llms_grounded_change_explanation_is_kept() -> None:
    explanation = await explain_plan(
        FakeProvider([GROUNDED]), amended(), request=AFTER, policy=POLICY
    )

    assert explanation.source is ExplanationSource.LLM
    assert explanation.changes == GROUNDED.changes


async def test_the_llm_is_shown_the_diff_and_the_request_changes_but_not_the_amendment() -> None:
    data = plan_data(amended(), request=AFTER, policy=POLICY)

    changes = data["changes_from_previous"]
    assert isinstance(changes, dict)
    assert changes["from_revision"] == 1
    assert changes["request_changes"] == [
        {"field": "marketing_budget", "before": "₹10 lakh", "after": "₹6 lakh"}
    ]
    assert [(r["sku_id"], r["region"]) for r in changes["lines_removed"]] == [("SKU0002", "West")]
    assert changes["objective"] == {
        "before": "₹3.7 lakh",
        "after": "₹2.5 lakh",
        "change": "-₹1.2 lakh",
    }
    assert "changes_from_previous" not in plan_data(FIRST, request=BEFORE, policy=POLICY)


async def test_an_ungrounded_change_explanation_is_regenerated_naming_its_numbers() -> None:
    invented = GROUNDED.model_copy(update={"changes": "The budget fell by ₹9 lakh."})
    llm = FakeProvider([invented, GROUNDED])

    explanation = await explain_plan(llm, amended(), request=AFTER, policy=POLICY)

    assert explanation.changes == GROUNDED.changes
    assert "₹9 lakh" in llm.calls[1].messages[-1].content
    assert "what changed" in llm.calls[1].messages[-1].content


async def test_a_missing_change_explanation_is_invalid_and_falls_back_to_the_template() -> None:
    silent = GROUNDED.model_copy(update={"changes": None})
    llm = FakeProvider([silent, silent])

    explanation = await explain_plan(llm, amended(), request=AFTER, policy=POLICY)

    assert explanation.fallback_reason is FallbackReason.INVALID_ANSWER
    assert explanation.changes == template_explanations(amended()).changes


async def test_a_first_revision_has_no_change_explanation_whatever_the_llm_writes() -> None:
    first = FIRST.model_copy(update={"lines": FIRST.lines[:1]})

    explanation = await explain_plan(FakeProvider([GROUNDED]), first, request=BEFORE, policy=POLICY)

    assert explanation.source is ExplanationSource.LLM
    assert explanation.changes is None
    assert template_explanations(first).changes is None


def test_the_template_says_what_changed_from_the_diff() -> None:
    changes = template_explanations(amended()).changes

    assert changes == (
        "Plan revision 2 changes plan revision 1. The planning request changed: "
        "the marketing budget from ₹10 lakh to ₹6 lakh. "
        "Removed: SKU0002 in West. 1 plan line is unchanged. "
        "The objective goes from ₹3.7 lakh to ₹2.5 lakh (down ₹1.2 lakh), and the promo cost "
        "from ₹7.5 lakh to ₹3 lakh (down ₹4.5 lakh)."
    )


AMOUNTS = st.floats(min_value=0, max_value=5e7, allow_nan=False)


@settings(max_examples=50)
@given(AMOUNTS, AMOUNTS, AMOUNTS, AMOUNTS)
def test_the_template_change_explanation_always_passes_grounding(
    cost: float, profit: float, budget: float, objective: float
) -> None:
    current = PlanRevision(
        number=2,
        lines=(
            line("SKU0001", Region.NORTH, cost, profit),
            line("SKU0003", Region.WEST, profit, cost),
        ),
        solver_status=SolveStatus.OPTIMAL,
        objective=objective,
    )
    request = AFTER.model_copy(update={"marketing_budget": budget + 1.0})
    diff = diff_revisions(FIRST, current, previous_request=BEFORE, request=request)
    revision = current.model_copy(update={"diff": diff})

    changes = template_explanations(revision).changes

    assert changes is not None
    data = plan_data(revision, request=request, policy=POLICY)
    assert check_numeric_grounding(changes, data).grounded


def test_the_explainer_prompt_is_versioned_and_asks_what_changed() -> None:
    prompt = explainer_prompt()

    assert prompt.startswith("<!-- prompt: explainer v2")
    assert "changes_from_previous" in prompt
