"""Display formats for explanations (ADR 0050): money in lakh or crore, percentages and units,
each rounded so that numeric grounding (ADR 0028) always accepts it for the value it shows."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from promopilot.guardrails import (
    check_numeric_grounding,
    format_percent,
    format_rupees,
    format_units,
)


@pytest.mark.parametrize(
    ("amount", "shown"),
    [
        (0.0, "₹0"),
        (-0.3, "₹0"),
        (183.45, "₹183"),
        (18_250.4, "₹18,250"),
        (-13_812.6, "-₹13,813"),
        (99_999.4, "₹99,999"),
        (99_999.6, "₹1 lakh"),
        (1_00_000.0, "₹1 lakh"),
        (1_72_384.2, "₹1.72 lakh"),
        (6_20_000.0, "₹6.2 lakh"),
        (-2_24_100.0, "-₹2.24 lakh"),
        (99_99_700.0, "₹1 crore"),
        (1_25_40_000.0, "₹1.25 crore"),
        (12_34_56_78_901.0, "₹1,234.57 crore"),
    ],
)
def test_money_is_whole_rupees_below_a_lakh_then_lakh_then_crore(amount: float, shown: str) -> None:
    assert format_rupees(amount) == shown


@pytest.mark.parametrize(
    ("fraction", "shown"),
    [(0.2237, "22.4%"), (0.25, "25%"), (0.9, "90%"), (0.7027, "70.3%"), (-0.031, "-3.1%")],
)
def test_percentages_have_at_most_one_decimal(fraction: float, shown: str) -> None:
    assert format_percent(fraction) == shown


@pytest.mark.parametrize(
    ("units", "shown"), [(412.4, "412"), (12_866.0, "12,866"), (1_23_456.5, "1,23,456")]
)
def test_units_are_whole_with_indian_grouping(units: float, shown: str) -> None:
    assert format_units(units) == shown


@settings(max_examples=500, deadline=None)
@given(st.floats(min_value=-1e11, max_value=1e11, allow_nan=False))
def test_formatted_money_always_passes_grounding_for_its_amount(amount: float) -> None:
    text = f"It costs {format_rupees(amount)}."

    assert check_numeric_grounding(text, [amount]).grounded, text


@settings(max_examples=500, deadline=None)
@given(st.floats(min_value=-5, max_value=5, allow_nan=False))
def test_formatted_percentages_always_pass_grounding_for_their_fraction(fraction: float) -> None:
    text = f"A margin of {format_percent(fraction)}."

    assert check_numeric_grounding(text, [fraction]).grounded, text


@settings(max_examples=300, deadline=None)
@given(st.floats(min_value=0, max_value=1e9, allow_nan=False))
def test_formatted_units_always_pass_grounding_for_their_count(units: float) -> None:
    text = f"About {format_units(units)} units."

    assert check_numeric_grounding(text, [units]).grounded, text
