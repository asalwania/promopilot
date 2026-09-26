"""Retry with exponential backoff and primary-to-secondary fallback (SPEC SF-03, ADR 0027).

A fake clock records each backoff instead of sleeping, so no test waits.
"""

import pytest
from pydantic import BaseModel

from promopilot.config import DEFAULT_LLM_PRICES
from promopilot.llm import (
    FakeProvider,
    FallbackProvider,
    LLMError,
    Message,
    RetryingProvider,
    ToolSpec,
    ToolTurn,
    TransientLLMError,
    track_usage,
)
from tests.unit.llm.test_anthropic_provider import FakeAnthropic, reply
from tests.unit.llm.test_openai_provider import FakeOpenAI


class Weather(BaseModel):
    city: str
    celsius: int


ASK = [Message(role="user", content="Pune, 31")]
PUNE = Weather(city="Pune", celsius=31)
FORECAST = ToolSpec(name="get_forecast", description="Forecast.", input_schema={"type": "object"})


class FakeClock:
    def __init__(self) -> None:
        self.sleeps: list[float] = []

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)


def retrying(inner: FakeProvider, clock: FakeClock, **bounds: float) -> RetryingProvider:
    return RetryingProvider(inner, sleep=clock.sleep, **bounds)  # type: ignore[arg-type]


async def test_transient_errors_are_retried_with_doubling_backoff() -> None:
    clock = FakeClock()
    inner = FakeProvider([TransientLLMError("429"), TransientLLMError("503"), PUNE])

    answer = await retrying(inner, clock).complete_structured(Weather, ASK)

    assert answer == PUNE
    assert clock.sleeps == [1.0, 2.0]
    assert len(inner.calls) == 3


async def test_retries_stop_at_the_attempt_bound_and_raise_the_last_error() -> None:
    clock = FakeClock()
    inner = FakeProvider([TransientLLMError(f"503 #{n}") for n in (1, 2, 3)] + [PUNE])

    with pytest.raises(TransientLLMError, match="503 #3"):
        await retrying(inner, clock).complete_structured(Weather, ASK)

    assert len(inner.calls) == 3
    assert clock.sleeps == [1.0, 2.0]


async def test_backoff_is_capped() -> None:
    clock = FakeClock()
    inner = FakeProvider([TransientLLMError("503")] * 5 + [PUNE])

    await retrying(inner, clock, max_attempts=6).complete_structured(Weather, ASK)

    assert clock.sleeps == [1.0, 2.0, 4.0, 8.0, 8.0]


async def test_a_permanent_error_is_not_retried() -> None:
    clock = FakeClock()
    inner = FakeProvider([LLMError("401 bad key"), PUNE])

    with pytest.raises(LLMError, match="401"):
        await retrying(inner, clock).complete_structured(Weather, ASK)

    assert clock.sleeps == []
    assert len(inner.calls) == 1


async def test_tool_calls_are_retried_too() -> None:
    clock = FakeClock()
    inner = FakeProvider([TransientLLMError("timeout"), ToolTurn(text="done")])

    turn = await retrying(inner, clock).complete_with_tools([FORECAST], ASK)

    assert turn == ToolTurn(text="done")
    assert clock.sleeps == [1.0]


async def test_after_the_primary_exhausts_its_retries_the_secondary_answers() -> None:
    clock = FakeClock()
    primary = FakeProvider([TransientLLMError("529 overloaded")] * 3)
    secondary = FakeProvider([PUNE])
    llm = FallbackProvider(retrying(primary, clock), retrying(secondary, clock))

    answer = await llm.complete_structured(Weather, ASK)

    assert answer == PUNE
    assert len(primary.calls) == 3
    assert len(secondary.calls) == 1
    assert secondary.calls[0].messages == ASK


async def test_a_permanent_primary_failure_also_falls_back() -> None:
    primary = FakeProvider([LLMError("401 bad key")])
    secondary = FakeProvider([ToolTurn(text="from secondary")])

    turn = await FallbackProvider(primary, secondary).complete_with_tools([FORECAST], ASK)

    assert turn == ToolTurn(text="from secondary")


async def test_when_both_providers_fail_the_error_names_both() -> None:
    primary = FakeProvider([LLMError("openai down")])
    secondary = FakeProvider([LLMError("anthropic down")])

    with pytest.raises(LLMError, match=r"openai down.*anthropic down"):
        await FallbackProvider(primary, secondary).complete_structured(Weather, ASK)


async def test_the_primary_answering_never_touches_the_secondary() -> None:
    secondary = FakeProvider([])

    answer = await FallbackProvider(FakeProvider([PUNE]), secondary).complete_structured(
        Weather, ASK
    )

    assert answer == PUNE
    assert secondary.calls == []


async def test_openai_overloaded_falls_back_to_claude_and_the_session_is_billed_for_claude() -> (
    None
):
    clock = FakeClock()
    openai_api = FakeOpenAI(503, {"error": {"message": "overloaded", "type": "server_error"}})
    claude_api = FakeAnthropic(
        200, reply([{"type": "text", "text": '{"city":"Pune","celsius":31}'}])
    )
    llm = FallbackProvider(
        RetryingProvider(openai_api.provider(model="gpt-4.1-mini"), sleep=clock.sleep),
        RetryingProvider(claude_api.provider(model="claude-sonnet-5"), sleep=clock.sleep),
    )

    with track_usage() as session:
        answer = await llm.complete_structured(Weather, ASK)

    assert answer == PUNE
    assert len(openai_api.requests) == 3
    assert clock.sleeps == [1.0, 2.0]
    totals = session.totals(DEFAULT_LLM_PRICES, usd_inr_rate=96.0)
    # One Claude call: 40 in x $2/M + 15 out x $10/M = $0.00008 + $0.00015 = $0.00023.
    assert (totals.calls, totals.input_tokens, totals.output_tokens) == (1, 40, 15)
    assert totals.cost_usd == pytest.approx(0.00023)
