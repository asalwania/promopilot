import pytest
from pydantic import BaseModel

from promopilot.llm import FakeProvider, LLMError, Message, ToolCall, ToolSpec, ToolTurn


class Weather(BaseModel):
    city: str
    celsius: int


ASK = [Message(role="system", content="Extract."), Message(role="user", content="Pune, 31")]


async def test_fake_provider_returns_its_script_in_order_and_records_calls() -> None:
    llm = FakeProvider([Weather(city="Pune", celsius=31), Weather(city="Goa", celsius=29)])

    first = await llm.complete_structured(Weather, ASK)
    second = await llm.complete_structured(Weather, [Message(role="user", content="Goa")])

    assert (first, second) == (Weather(city="Pune", celsius=31), Weather(city="Goa", celsius=29))
    assert [call.schema for call in llm.calls] == [Weather, Weather]
    assert llm.calls[0].messages == ASK
    assert llm.calls[1].messages == [Message(role="user", content="Goa")]


async def test_fake_provider_raises_a_scripted_error() -> None:
    llm = FakeProvider([LLMError("provider down")])

    with pytest.raises(LLMError, match="provider down"):
        await llm.complete_structured(Weather, ASK)


async def test_fake_provider_fails_loudly_when_its_script_runs_out() -> None:
    llm = FakeProvider([])

    with pytest.raises(AssertionError, match="script exhausted"):
        await llm.complete_structured(Weather, ASK)


async def test_fake_provider_rejects_a_scripted_response_of_the_wrong_schema() -> None:
    class Other(BaseModel):
        note: str

    llm = FakeProvider([Other(note="x")])

    with pytest.raises(AssertionError, match="scripted Other, but Weather asked"):
        await llm.complete_structured(Weather, ASK)


FORECAST = ToolSpec(
    name="get_forecast",
    description="Forecast for a city.",
    input_schema={"type": "object", "properties": {"city": {"type": "string"}}},
)


async def test_fake_provider_answers_tool_calls_from_its_script_and_records_the_tools() -> None:
    turn = ToolTurn(
        tool_calls=(ToolCall(id="call_1", name="get_forecast", arguments={"city": "Pune"}),)
    )
    llm = FakeProvider([turn])

    answer = await llm.complete_with_tools([FORECAST], ASK)

    assert answer == turn
    assert llm.calls[0].tools == (FORECAST,)
    assert llm.calls[0].schema is None
    assert llm.calls[0].messages == ASK


async def test_fake_provider_rejects_a_structured_answer_scripted_for_a_tool_call() -> None:
    llm = FakeProvider([Weather(city="Pune", celsius=31)])

    with pytest.raises(AssertionError, match="scripted Weather, but a tool turn asked"):
        await llm.complete_with_tools([FORECAST], ASK)
