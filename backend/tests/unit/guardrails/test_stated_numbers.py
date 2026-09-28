"""`read_stated_numbers`: the rupee amounts and percentages a brief states, read by strict rules
for the Context agent's fallback reading when the LLM is down (ADR 0053)."""

import pytest

from promopilot.guardrails import StatedKind, read_stated_numbers


def values(text: str, **options: object) -> list[tuple[StatedKind, float, str]]:
    return [(n.kind, n.value, n.text) for n in read_stated_numbers(text, **options)]  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("Budget ₹8 lakh.", 800_000.0),
        ("a marketing budget of ₹2 lakh", 200_000.0),
        ("₹2L for the push", 200_000.0),
        ("₹1.5 crore overall", 15_000_000.0),
        ("₹1.5Cr overall", 15_000_000.0),
        ("₹90k for North", 90_000.0),
        ("₹20K", 20_000.0),
        ("Rs. 50,000 to spend", 50_000.0),
        ("Rs 5,00,000 to spend", 500_000.0),
        ("INR 75000", 75_000.0),
        ("2 lakh budget", 200_000.0),
        ("3 lakhs", 300_000.0),
        ("2.3 lakh", 230_000.0),
        ("₹18,250", 18_250.0),
    ],
)
def test_rupee_amounts_are_read_in_rupees(text: str, value: float) -> None:
    assert [(kind, amount) for kind, amount, _ in values(text)] == [(StatedKind.RUPEES, value)]


@pytest.mark.parametrize(
    ("text", "fraction"),
    [
        ("Keep margin above 18%.", 0.18),
        ("clear at least 60% of that stock", 0.6),
        ("within 2.5 per cent of the competitor", 0.025),
        ("7 percent", 0.07),
    ],
)
def test_percentages_are_read_as_fractions(text: str, fraction: float) -> None:
    assert [(kind, amount) for kind, amount, _ in values(text)] == [(StatedKind.PERCENT, fraction)]


@pytest.mark.parametrize(
    "text",
    [
        "400g namkeen packs",
        "2L cola bottles",
        "90k units",
        "SKU0002 and SKU0006",
        "weeks 108-109",
        "the top 3 SKUs",
        "Diwali 2026 on 12 Nov",
    ],
)
def test_numbers_that_are_not_money_or_percentages_are_not_read(text: str) -> None:
    assert values(text) == []


def test_each_number_keeps_where_it_was_written() -> None:
    text = "Budget ₹8 lakh. Keep margin above 18%."

    [budget, margin] = read_stated_numbers(text)

    assert text[budget.start : budget.end] == budget.text == "₹8 lakh"
    assert text[margin.start : margin.end] == margin.text == "18%"


def test_an_answer_may_state_bare_numbers_in_the_unit_it_was_asked_in() -> None:
    assert values("500000", bare=StatedKind.RUPEES) == [(StatedKind.RUPEES, 500_000.0, "500000")]
    assert values("5 lakh", bare=StatedKind.RUPEES) == [(StatedKind.RUPEES, 500_000.0, "5 lakh")]
    assert values("18", bare=StatedKind.PERCENT) == [(StatedKind.PERCENT, 0.18, "18")]
    # Numbers inside words stay unread even then.
    assert values("SKU0002", bare=StatedKind.RUPEES) == []
