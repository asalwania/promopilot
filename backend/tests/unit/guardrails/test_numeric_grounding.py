"""`check_numeric_grounding`: every number in a text must come from tool outputs (ADR 0028)."""

import pytest
from pydantic import BaseModel

from promopilot.guardrails import GroundingReport, check_numeric_grounding

TOOL_OUTPUTS = {
    "plan": {
        "total_promo_cost": 618_432.5,
        "objective": 10_960_000.0,
        "blended_margin": 0.1804,
        "lines": [
            {"sku_id": "SKU-0042", "depth_pct": 25, "expected_units": 1_234.4},
            {"sku_id": "SKU-0107", "depth_pct": 18, "expected_incremental_profit": -12_000.4},
        ],
    },
    "notes": ["Diwali week starts 12 Oct; 1,250 units of 400g namkeen on hand"],
}


def ungrounded(text: str, tool_outputs: object = TOOL_OUTPUTS) -> tuple[str, ...]:
    return check_numeric_grounding(text, tool_outputs).ungrounded


@pytest.mark.parametrize(
    "text",
    [
        "Total promo cost is ₹6.2 lakh.",
        "Total promo cost is ₹6 lakh.",
        "Total promo cost is Rs. 6.18 lakhs.",
        "Expected profit is ₹1.1 crore.",
        "Expected profit is ₹1.10 crore.",
        "Blended margin is 18%.",
        "Blended margin is 18.0 percent.",
        "SKU-0107 gets 18% off.",
        "About 1,234 units are expected.",
        "Promo cost ₹6,18,433 in Indian grouping.",
        "Promo cost ₹618,433 in Western grouping.",
        "Promo cost ₹618432.5 exactly.",
        "It loses ₹12,000 on this line.",
        "Its incremental profit is −₹12,000.",  # noqa: RUF001 (a Unicode minus sign)
        "Its incremental profit is -12,000 rupees.",
        "Stock on hand is 1,250 units.",
    ],
)
def test_rounded_numbers_present_in_tool_outputs_are_grounded(text: str) -> None:
    assert ungrounded(text) == ()


@pytest.mark.parametrize(
    ("text", "invented"),
    [
        ("Total promo cost is ₹6.3 lakh.", "₹6.3 lakh"),
        ("Total promo cost is ₹7 lakh.", "₹7 lakh"),
        ("Total promo cost is ₹6.20 lakh.", "₹6.20 lakh"),  # 2 decimals: ±₹500, not ±₹5,000
        ("Expected profit is ₹1.2 crore.", "₹1.2 crore"),
        ("Blended margin is 21%.", "21%"),
        ("We expect 1,500 extra units.", "1,500"),
        ("It saves ₹999.", "₹999"),
        ("Uplift is 0.35 times baseline.", "0.35"),
        ("Promo cost ₹6,18,000.", "₹6,18,000"),  # a whole number is exact to the rupee
        ("We promote 11 regions.", "11"),
        ("Only 3% more.", "3%"),
        ("Just ₹5 off.", "₹5"),
    ],
)
def test_invented_numbers_are_rejected(text: str, invented: str) -> None:
    assert ungrounded(text) == (invented,)


def test_every_invented_number_is_reported_in_order() -> None:
    text = "Spend ₹9 lakh for 42.5% margin and ₹6.2 lakh on top."

    assert ungrounded(text) == ("₹9 lakh", "42.5%")


@pytest.mark.parametrize(
    "text",
    [
        "Promote SKU-0042 and SKU_77 in W12.",
        "Clear the 400g namkeen packs and the 2L bottles.",
        "Starts on 2026-10-12, runs 12 Oct to 19 October 2026, or 12/10/2026.",
        "From Oct 12, 2026 to November 2nd.",
        "Plan for Diwali 2026.",
        "Across 3 regions, 2 categories and 10 weeks; line 1 of 4.",
        "Use model v1.2 for the 3rd time.",
    ],
)
def test_identifiers_dates_years_and_small_counts_are_exempt(text: str) -> None:
    assert ungrounded(text, {}) == ()


def test_a_week_number_is_not_exempt_but_grounds_on_tool_outputs() -> None:
    assert ungrounded("Starts in week 112.", {}) == ("112",)
    assert ungrounded("Starts in week 112.", {"start_week": 112}) == ()


def test_numbers_inside_tool_output_strings_ground_the_text() -> None:
    outputs = {"summary": "Budget ₹8 lakh, margin above 18%"}

    assert ungrounded("Budget ₹8 lakh; margin 18%.", outputs) == ()
    assert ungrounded("Budget ₹800000.", outputs) == ()


def test_tool_outputs_may_be_pydantic_models_and_nested_sequences() -> None:
    class Line(BaseModel):
        promo_cost: float

    outputs = [(Line(promo_cost=24_150.0),), {"totals": [Line(promo_cost=51_000.0)]}]

    assert ungrounded("₹24,150 and ₹51 thousand-ish: ₹51,000.", outputs) == ("₹51",)


def test_booleans_in_tool_outputs_are_not_numbers() -> None:
    assert ungrounded("It costs ₹1.", {"flag": True}) == ("₹1",)


def test_a_grounded_text_passes() -> None:
    report = check_numeric_grounding("Margin 18%, cost ₹6.2 lakh.", TOOL_OUTPUTS)

    assert report == GroundingReport(ungrounded=())
    assert report.grounded


def test_an_ungrounded_text_fails() -> None:
    assert not check_numeric_grounding("Margin 47%.", TOOL_OUTPUTS).grounded


def test_text_without_numbers_is_grounded() -> None:
    assert check_numeric_grounding("Promote the namkeen packs in North.", {}).grounded
