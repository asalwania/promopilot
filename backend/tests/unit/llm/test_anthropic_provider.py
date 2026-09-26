"""AnthropicProvider at the HTTP boundary: a mock transport stands in for api.anthropic.com.

anthropic 1.x speaks HTTP through `httpx2`, so the mock transport comes from there.
"""

import json
from typing import Any

import anthropic
import httpx2 as httpx
import pytest
from pydantic import BaseModel

from promopilot.llm import (
    AnthropicProvider,
    LLMError,
    Message,
    ToolCall,
    ToolSpec,
    ToolTurn,
    TransientLLMError,
    Usage,
    track_usage,
)

SECRET_KEY = "sk-ant-test-do-not-leak"


class Weather(BaseModel):
    city: str
    celsius: int


ASK = [Message(role="system", content="Extract."), Message(role="user", content="Pune, 31")]
THINKING = {"type": "thinking", "thinking": "", "signature": "sig-abc"}
FORECAST = ToolSpec(
    name="get_forecast",
    description="Forecast for a city.",
    input_schema={"type": "object", "properties": {"city": {"type": "string"}}},
)


def reply(content: list[dict[str, Any]], stop_reason: str = "end_turn") -> dict[str, Any]:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 40, "output_tokens": 15},
    }


class FakeAnthropic:
    """Records the requests the SDK sends and answers each with one canned response."""

    def __init__(self, status: int, body: dict[str, Any]) -> None:
        self.status, self.body = status, body
        self.requests: list[httpx.Request] = []

    def provider(self, model: str = "claude-sonnet-5") -> AnthropicProvider:
        def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return httpx.Response(self.status, json=self.body)

        client = anthropic.AsyncAnthropic(
            api_key=SECRET_KEY,
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        )
        return AnthropicProvider(client, model=model)

    def sent(self) -> dict[str, Any]:
        body: dict[str, Any] = json.loads(self.requests[0].content)
        return body


async def test_a_structured_answer_is_parsed() -> None:
    api = FakeAnthropic(200, reply([{"type": "text", "text": '{"city":"Pune","celsius":31}'}]))

    assert await api.provider().complete_structured(Weather, ASK) == Weather(
        city="Pune", celsius=31
    )


async def test_a_structured_request_uses_a_schema_low_effort_and_no_temperature() -> None:
    api = FakeAnthropic(200, reply([{"type": "text", "text": '{"city":"Pune","celsius":31}'}]))

    await api.provider(model="claude-from-env").complete_structured(Weather, ASK)

    sent = api.sent()
    assert sent["model"] == "claude-from-env"
    assert "temperature" not in sent  # claude-sonnet-5 rejects sampling parameters
    assert sent["thinking"] == {"type": "adaptive"}
    assert sent["output_config"]["effort"] == "low"
    assert sent["output_config"]["format"]["type"] == "json_schema"
    assert sent["system"] == "Extract."
    assert sent["messages"] == [{"role": "user", "content": "Pune, 31"}]


async def test_a_refusal_is_an_llm_error_and_is_still_billed() -> None:
    api = FakeAnthropic(200, reply([], stop_reason="refusal"))

    with track_usage() as meter, pytest.raises(LLMError, match="refus"):
        await api.provider().complete_structured(Weather, ASK)

    assert meter.usages == (Usage(model="claude-sonnet-5", input_tokens=40, output_tokens=15),)


async def test_an_unparseable_answer_is_an_llm_error() -> None:
    api = FakeAnthropic(200, reply([{"type": "text", "text": "not json"}]))

    with pytest.raises(LLMError):
        await api.provider().complete_structured(Weather, ASK)


@pytest.mark.parametrize("status", [408, 429, 500, 529])
async def test_retryable_statuses_surface_as_transient_errors(status: int) -> None:
    api = FakeAnthropic(status, {"type": "error", "error": {"type": "overloaded_error"}})

    with pytest.raises(TransientLLMError):
        await api.provider().complete_structured(Weather, ASK)


@pytest.mark.parametrize("status", [400, 401])
async def test_client_errors_are_permanent(status: int) -> None:
    api = FakeAnthropic(status, {"type": "error", "error": {"type": "invalid_request_error"}})

    with pytest.raises(LLMError) as raised:
        await api.provider().complete_structured(Weather, ASK)

    assert not isinstance(raised.value, TransientLLMError)


async def test_a_dropped_connection_is_transient() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = anthropic.AsyncAnthropic(
        api_key=SECRET_KEY,
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(refuse)),
    )

    with pytest.raises(TransientLLMError):
        await AnthropicProvider(client, model="claude-sonnet-5").complete_structured(Weather, ASK)


async def test_a_tool_turn_returns_calls_text_and_the_thinking_to_echo_back() -> None:
    api = FakeAnthropic(
        200,
        reply(
            [
                THINKING,
                {"type": "text", "text": "Checking the forecast."},
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "get_forecast",
                    "input": {"city": "Pune"},
                },
            ],
            stop_reason="tool_use",
        ),
    )

    with track_usage() as meter:
        turn = await api.provider().complete_with_tools([FORECAST], ASK)

    assert turn == ToolTurn(
        text="Checking the forecast.",
        tool_calls=(ToolCall(id="toolu_1", name="get_forecast", arguments={"city": "Pune"}),),
        provider_state=(THINKING,),
    )
    assert [u.input_tokens for u in meter.usages] == [40]


async def test_a_tool_round_goes_out_as_tool_use_and_one_user_turn_of_tool_results() -> None:
    api = FakeAnthropic(200, reply([{"type": "text", "text": "31 C and 29 C."}]))
    pune = ToolCall(id="toolu_1", name="get_forecast", arguments={"city": "Pune"})
    goa = ToolCall(id="toolu_2", name="get_forecast", arguments={"city": "Goa"})
    asked = ToolTurn(text="Checking.", tool_calls=(pune, goa), provider_state=(THINKING,))
    round_ = [
        *ASK,
        asked.as_message(),
        Message(role="tool", content='{"celsius": 31}', tool_call_id="toolu_1"),
        Message(role="tool", content='{"celsius": 29}', tool_call_id="toolu_2"),
    ]

    turn = await api.provider().complete_with_tools([FORECAST], round_)

    assert turn == ToolTurn(text="31 C and 29 C.")
    sent = api.sent()
    assert "temperature" not in sent
    assert sent["tools"] == [
        {
            "name": "get_forecast",
            "description": "Forecast for a city.",
            "input_schema": FORECAST.input_schema,
        }
    ]
    assert sent["messages"] == [
        {"role": "user", "content": "Pune, 31"},
        {
            "role": "assistant",
            "content": [
                THINKING,
                {"type": "text", "text": "Checking."},
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "get_forecast",
                    "input": {"city": "Pune"},
                },
                {
                    "type": "tool_use",
                    "id": "toolu_2",
                    "name": "get_forecast",
                    "input": {"city": "Goa"},
                },
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "toolu_1", "content": '{"celsius": 31}'},
                {"type": "tool_result", "tool_use_id": "toolu_2", "content": '{"celsius": 29}'},
            ],
        },
    ]
