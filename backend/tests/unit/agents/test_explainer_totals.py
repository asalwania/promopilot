"""The Explainer is shown the totals it would otherwise add up itself (#185, ADR 0090): the
LLM never computes numbers, and a figure it derives (the sum of the lines' incremental profit,
the budget left unspent) is ungrounded, so the answer falls back to the template."""

from promopilot.agents import (
    ExplainerAnswer,
    LineRationale,
    explain_plan,
    explainer_prompt,
    plan_data,
)
from promopilot.domain import (
    ClearanceShortfall,
    ExplanationSource,
    Mechanism,
    PlanLine,
    PlanningRequest,
    PlanRevision,
    PlanRevisionLine,
    PlanSafetyMargin,
    PromoWindow,
    Region,
    Scope,
    SolveStatus,
    TargetSegment,
)
from promopilot.llm import FakeProvider
from tests.unit.agents.test_graph import POLICY

REQUEST = PlanningRequest(
    as_of_week=52,
    scope=Scope(regions=(Region.NORTH,), categories=("Snacks",)),
    promo_window=PromoWindow(start_week=54, end_week=55),
    marketing_budget=10_000.0,
)


def line(sku_id: str, units: float, cost: float, profit: float) -> PlanRevisionLine:
    return PlanRevisionLine(
        line=PlanLine(
            sku_id=sku_id,
            region=Region.NORTH,
            mechanism=Mechanism.FIXED_PRICE,
            depth_pct=5,
            duration_weeks=2,
            start_week=54,
            target_segment=TargetSegment.ALL_CUSTOMERS,
        ),
        expected_units=units,
        promo_cost=cost,
        expected_incremental_profit=profit,
    )


def shortfall(sku_id: str, units: float) -> ClearanceShortfall:
    return ClearanceShortfall(
        sku_id=sku_id,
        region=Region.NORTH,
        target=0.95,
        expected_sell_through=0.4,
        shortfall_units=units,
    )


def revision(**update: object) -> PlanRevision:
    # The two lines of the recorded infeasible session (#142): shown as ₹3,934 + ₹4,697 and
    # ₹4,415 + ₹489, which the LLM added up to ₹8,631 and ₹4,904 (#185).
    return PlanRevision(
        number=1,
        lines=(
            line("SKU0002", 586.6, 3_934.4, 4_415.3),
            line("SKU0006", 335.6, 4_697.2, 489.4),
        ),
        solver_status=SolveStatus.INFEASIBLE,
        objective=12_184.0,
        safety_margin=PlanSafetyMargin(budget_quantile=0.9, planned_promo_cost=9_513.0),
        clearance_shortfalls=(shortfall("SKU0002", 777.6), shortfall("SKU0006", 543.6)),
    ).model_copy(update=update)


def answering(summary: str) -> ExplainerAnswer:
    return ExplainerAnswer(
        summary=summary,
        rationales=[
            LineRationale(line=1, rationale="SKU0002 at 5% fixed price."),
            LineRationale(line=2, rationale="SKU0006 at 5% fixed price."),
        ],
    )


def totals(plan: PlanRevision) -> dict[str, object]:
    shown = plan_data(plan, request=REQUEST, policy=POLICY)["plan_totals"]
    assert isinstance(shown, dict)
    return shown


def test_the_plan_totals_add_up_the_amounts_as_the_lines_show_them() -> None:
    # 3,934.4 + 4,697.2 is 8,631.6, but the lines show ₹3,934 and ₹4,697: the total an
    # LLM adding them up reaches is the one shown.
    assert totals(revision()) == {
        "expected_units": "923",
        "promo_cost": "₹8,631",
        "expected_incremental_profit": "₹4,904",
        "marketing_budget_left_at_expected_promo_cost": "₹1,369",
        "marketing_budget_left_at_planned_promo_cost": "₹487",
        "clearance_shortfall_units": "1,322",
    }


def test_no_budget_is_left_at_the_planned_promo_cost_of_a_plan_without_a_safety_margin() -> None:
    assert "marketing_budget_left_at_planned_promo_cost" not in totals(revision(safety_margin=None))


def test_a_plan_without_lines_totals_nothing() -> None:
    assert totals(revision(lines=(), clearance_shortfalls=(), safety_margin=None)) == {
        "expected_units": "0",
        "promo_cost": "₹0",
        "expected_incremental_profit": "₹0",
        "marketing_budget_left_at_expected_promo_cost": "₹10,000",
        "clearance_shortfall_units": "0",
    }


async def test_an_answer_citing_the_totals_is_grounded() -> None:
    summary = (
        "The plan is infeasible: it is expected to add ₹4,904 of incremental profit for "
        "₹8,631 of promo cost, leaving ₹1,369 of the ₹10,000 budget unspent (₹487 at the "
        "planned cost), and is 1,322 "
        "units short of the clearance targets."
    )
    llm = FakeProvider([answering(summary)])

    explanation = await explain_plan(llm, revision(), request=REQUEST, policy=POLICY)

    assert explanation.source is ExplanationSource.LLM
    assert explanation.summary.endswith(summary)
    assert len(llm.calls) == 1


async def test_a_total_the_data_does_not_show_is_still_ungrounded() -> None:
    summary = "The plan adds ₹4,905 of incremental profit."
    llm = FakeProvider([answering(summary), answering(summary)])

    explanation = await explain_plan(llm, revision(), request=REQUEST, policy=POLICY)

    assert explanation.source is ExplanationSource.TEMPLATE
    assert len(llm.calls) == 2


def test_the_prompt_sends_the_llm_to_the_totals_and_forbids_working_out_others() -> None:
    prompt = explainer_prompt()

    assert "plan_totals" in prompt
    assert "never add up" in prompt.lower()
