"""The Context agent's fallback reading (SF-03, #124, ADR 0053): with the LLM down, the brief,
the manager's answers and any amendments are read by deterministic rules into the same
planning request, assumptions and questions, and the LLM is never asked again."""

import pytest

from promopilot.agents import (
    ContextReading,
    DegradedReason,
    read_context,
    read_planning_request,
)
from promopilot.agents.session import BriefData
from promopilot.datagen import GeneratedDataset
from promopilot.domain import (
    Assumption,
    AssumptionSource,
    Clarification,
    ClarificationQuestion,
    CompanyPolicy,
    PromoWindow,
    QuestionReason,
    Region,
)
from promopilot.llm import CassetteMissError, FakeProvider, LLMError
from tests.unit.agents.fakes import InMemoryRetailData

POLICY = CompanyPolicy()
DEMO_BRIEF = (  # cassettes/briefs.json
    "Plan a Diwali promotion for Snacks and Beverages in North and West. Run it for the two "
    "weeks leading up to Diwali, with a marketing budget of ₹2 lakh."
)
SPEC_BRIEF = (  # SPEC §3.2
    "Plan Diwali promotions for Snacks and Beverages across North and West. Budget ₹8 lakh. "
    "Keep margin above 18%. We are overstocked on 400g namkeen packs — clear at least 60% of "
    "that stock. Target families."
)
SMALL_BRIEF = "Snacks push in the North, ₹20k, weeks 54-55"  # the small world's as-of week is 52
CRITICAL = {"scope.regions", "scope.categories", "promo_window", "marketing_budget"}


@pytest.fixture
def small(small_dataset: GeneratedDataset) -> InMemoryRetailData:
    return InMemoryRetailData(small_dataset)


@pytest.fixture
def demo(default_dataset: GeneratedDataset) -> InMemoryRetailData:
    return InMemoryRetailData(default_dataset)


async def read_down(
    brief: str,
    data: BriefData,
    *,
    clarifications: tuple[Clarification, ...] = (),
    amendments: tuple[str, ...] = (),
    down: LLMError | None = None,
) -> ContextReading:
    llm = FakeProvider([down or LLMError("provider down")])
    reading = await read_context(
        brief,
        llm,
        data,
        policy=POLICY,
        clarifications=clarifications,
        amendments=amendments,
        fallback=True,
    )
    assert len(llm.calls) == 1, "the fallback never asks the LLM again"
    return reading


def by_field(assumptions: tuple[Assumption, ...]) -> dict[str, Assumption]:
    return {a.field: a for a in assumptions}


def questions_of(reading: ContextReading) -> dict[str, ClarificationQuestion]:
    return {q.id: q for q in reading.questions}


def answered(reading: ContextReading, **answers: str) -> tuple[Clarification, ...]:
    asked = questions_of(reading)
    return tuple(
        Clarification(question=asked[key.replace("__", ".")], answer=text)
        for key, text in answers.items()
    )


# --- acceptance: the demo brief reads by rules as the LLM read it ------------------------------


async def test_the_demo_brief_reads_by_rules_into_the_request_the_llm_read(
    demo: InMemoryRetailData,
) -> None:
    reading = await read_down(DEMO_BRIEF, demo)

    assert reading.questions == ()
    assert reading.degraded is DegradedReason.LLM_UNAVAILABLE
    request = reading.request
    assert request is not None
    # The committed cassette's reading of this brief (ADR 0048 D12).
    assert request.scope.regions == (Region.NORTH, Region.WEST)
    assert request.scope.categories == ("Snacks", "Beverages")
    assert request.promo_window == PromoWindow(start_week=108, end_week=109)
    assert request.marketing_budget == 200_000.0


async def test_every_assumption_of_a_fallback_reading_is_marked_and_what_it_read_is_low(
    demo: InMemoryRetailData,
) -> None:
    reading = await read_down(DEMO_BRIEF, demo)

    assert reading.assumptions
    assert all(a.fallback for a in reading.assumptions)
    assumed = by_field(reading.assumptions)
    for field in CRITICAL:
        # Low, yet at the AG-02 threshold: the demo still plans (ADR 0053 D6).
        assert assumed[field].confidence == 0.7
    assert assumed["promo_window"].source is AssumptionSource.DATA
    assert assumed["marketing_budget"].source is AssumptionSource.BRIEF
    # Data and company policy are as sure as ever.
    assert assumed["as_of_week"].confidence == 1.0
    assert assumed["min_margin"].source is AssumptionSource.DEFAULT
    assert assumed["min_margin"].confidence == 1.0


async def test_the_spec_brief_reads_fully(demo: InMemoryRetailData) -> None:
    reading = await read_down(SPEC_BRIEF, demo)

    assert reading.questions == ()
    request = reading.request
    assert request is not None
    assert request.marketing_budget == 800_000.0
    assert request.min_margin == 0.18
    assert {(t.sku_id, t.sell_through) for t in request.clearance_targets} == {
        ("SKU0002", 0.6),
        ("SKU0006", 0.6),
    }
    assumed = by_field(reading.assumptions)
    assert assumed["target_segment"].flagged
    assert "families" in (assumed["target_segment"].note or "")


async def test_a_cassette_miss_falls_back_too(small: InMemoryRetailData) -> None:
    reading = await read_down(SMALL_BRIEF, small, down=CassetteMissError("no cassette"))

    assert reading.degraded is DegradedReason.CASSETTE_MISSING
    assert reading.request is not None


async def test_an_llm_reading_is_not_degraded(small: InMemoryRetailData) -> None:
    from tests.unit.agents.test_context_agent import reading as llm_reading

    reading = await read_context(
        SMALL_BRIEF, FakeProvider([llm_reading()]), small, policy=POLICY, fallback=True
    )

    assert reading.degraded is None
    assert not any(a.fallback for a in reading.assumptions)


async def test_without_the_fallback_an_llm_error_still_fails_loudly(
    small: InMemoryRetailData,
) -> None:
    # Recording cassettes and the committed-cassette test must never pass on a miss.
    with pytest.raises(CassetteMissError):
        await read_context(
            SMALL_BRIEF, FakeProvider([CassetteMissError("miss")]), small, policy=POLICY
        )
    with pytest.raises(LLMError):
        await read_planning_request(SMALL_BRIEF, FakeProvider([LLMError("down")]), small)


# --- what the rules read ------------------------------------------------------------------------


async def test_a_brief_the_rules_cannot_read_asks_every_critical_field(
    small: InMemoryRetailData,
) -> None:
    reading = await read_down("Let's do something nice for the festive season", small)

    assert reading.request is None
    assert {q.field for q in reading.questions} == CRITICAL


async def test_caps_tolerance_and_the_sku_cap_are_read_from_their_cues(
    small: InMemoryRetailData,
) -> None:
    brief = (
        "Snacks in North and South for Diwali. Budget ₹2 lakh, with ₹90k for North. Keep KVIs "
        "within 3% of the competitor, margin above 20%. At most 2 SKUs per category."
    )

    reading = await read_down(brief, small)

    request = reading.request
    assert request is not None
    assert request.marketing_budget == 200_000.0
    assert request.regional_budget_caps == {Region.NORTH: 90_000.0}
    assert request.kvi_price_tolerance == 0.03
    assert request.min_margin == 0.2
    assert request.max_promoted_skus_per_category_per_region == 2
    assert request.promo_window == PromoWindow(start_week=54, end_week=55)


async def test_several_amounts_ask_which_is_the_budget(small: InMemoryRetailData) -> None:
    reading = await read_down("Snacks in the North for Diwali: ₹20k or ₹30k", small)

    question = questions_of(reading)["marketing_budget"]
    assert question.reason is QuestionReason.AMBIGUOUS
    assert question.suggestions == ("₹20k", "₹30k")


async def test_two_holidays_ask_which_window(small: InMemoryRetailData) -> None:
    reading = await read_down("Snacks in the North, ₹20k, for Diwali or Christmas", small)

    question = questions_of(reading)["promo_window"]
    assert question.reason is QuestionReason.AMBIGUOUS
    assert "Diwali" in question.question
    assert "Christmas" in question.question


@pytest.mark.parametrize("brief", ["Snacks in the North, 20k, weeks 54-55", "Snacks, North, 54-55"])
async def test_what_the_rules_cannot_be_sure_of_is_asked_not_guessed(
    small: InMemoryRetailData, brief: str
) -> None:
    reading = await read_down(brief, small)

    assert reading.request is None
    assert "marketing_budget" in questions_of(reading)


async def test_the_rules_read_every_region(small: InMemoryRetailData) -> None:
    reading = await read_down("A pan-India snacks push, ₹20k, weeks 54-55", small)

    assert reading.request is not None
    assert reading.request.scope.regions == (Region.NORTH, Region.SOUTH)


# --- answers and amendments ---------------------------------------------------------------------


async def test_answers_are_read_against_their_questions(small: InMemoryRetailData) -> None:
    brief = "Snacks push, weeks 54-55"
    first = await read_down(brief, small)
    assert set(questions_of(first)) == {"scope.regions", "marketing_budget"}

    second = await read_down(
        brief,
        small,
        clarifications=answered(first, scope__regions="Nort", marketing_budget="25000"),
    )

    assert second.questions == ()
    assert second.request is not None
    assert second.request.scope.regions == (Region.NORTH,)
    assert second.request.marketing_budget == 25_000.0


async def test_an_answer_the_rules_cannot_read_is_asked_again(small: InMemoryRetailData) -> None:
    brief = "Snacks in the North, weeks 54-55"
    first = await read_down(brief, small)

    second = await read_down(
        brief, small, clarifications=answered(first, marketing_budget="whatever you think")
    )

    question = questions_of(second)["marketing_budget"]
    assert question.reason is QuestionReason.LOW_CONFIDENCE
    assert "whatever you think" in question.question


async def test_amendments_change_what_they_state(small: InMemoryRetailData) -> None:
    brief = "Snacks and Beverages in North and South, ₹20k budget, weeks 54-55"

    reading = await read_down(brief, small, amendments=("cut budget to ₹15k", "drop South"))

    request = reading.request
    assert request is not None
    assert request.marketing_budget == 15_000.0
    assert request.scope.regions == (Region.NORTH,)
    assert request.scope.categories == ("Snacks", "Beverages")


async def test_an_amendment_the_rules_cannot_read_is_asked_and_its_answer_applies(
    small: InMemoryRetailData,
) -> None:
    brief = "Snacks in North and South, ₹20k budget, weeks 54-55"
    first = await read_down(brief, small, amendments=("make it punchier",))

    assert first.request is None
    [question] = first.questions
    assert (question.id, question.field) == ("amendment.0", "amendment")
    assert "make it punchier" in question.question

    second = await read_down(
        brief,
        small,
        amendments=("make it punchier",),
        clarifications=answered(first, amendment__0="drop South"),
    )

    assert second.request is not None
    assert second.request.scope.regions == (Region.NORTH,)
