"""OpenAIProvider at the HTTP boundary: a mock transport stands in for api.openai.com.

openai 3.x speaks HTTP through `httpx2`, so the mock transport comes from there.
"""

import json
from pathlib import Path
from typing import Any

import httpx2 as httpx
import pytest
from openai import AsyncOpenAI
from pydantic import BaseModel

from promopilot.llm import (
    LLMError,
    Message,
    OpenAIProvider,
    RecordingProvider,
    ToolCall,
    ToolSpec,
    ToolTurn,
    TransientLLMError,
    Usage,
    track_usage,
)

SECRET_KEY = "sk-test-do-not-leak-0123456789"


class Weather(BaseModel):
    city: str
    celsius: int


ASK = [Message(role="system", content="Extract."), Message(role="user", content="Pune, 31")]


def completion(content: str | None, refusal: str | None = None) -> dict[str, Any]:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1_790_000_000,
        "model": "gpt-test-2026",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content, "refusal": refusal},
            }
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
    }


class FakeOpenAI:
    """Records the requests the SDK sends and answers each with one canned response."""

    def __init__(self, status: int, body: dict[str, Any]) -> None:
        self.status, self.body = status, body
        self.requests: list[httpx.Request] = []

    def provider(self, model: str = "gpt-test-2026") -> OpenAIProvider:
        def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return httpx.Response(self.status, json=self.body)

        client = AsyncOpenAI(
            api_key=SECRET_KEY,
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        )
        return OpenAIProvider(client, model=model)


async def test_openai_provider_parses_the_structured_answer() -> None:
    api = FakeOpenAI(200, completion('{"city": "Pune", "celsius": 31}'))

    answer = await api.provider().complete_structured(Weather, ASK)

    assert answer == Weather(city="Pune", celsius=31)


async def test_openai_provider_sends_the_env_model_at_temperature_zero_with_a_json_schema() -> None:
    api = FakeOpenAI(200, completion('{"city": "Pune", "celsius": 31}'))

    await api.provider(model="gpt-from-env").complete_structured(Weather, ASK)

    sent = json.loads(api.requests[0].content)
    assert sent["model"] == "gpt-from-env"
    assert sent["temperature"] == 0
    assert sent["messages"] == [
        {"role": "system", "content": "Extract."},
        {"role": "user", "content": "Pune, 31"},
    ]
    assert sent["response_format"]["type"] == "json_schema"
    assert sent["response_format"]["json_schema"]["name"] == "Weather"


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (500, {"error": {"message": "server exploded", "type": "server_error"}}),
        (200, completion("not json at all")),
        (200, completion(None, refusal="I cannot help with that.")),
    ],
    ids=["api-error", "unparseable-answer", "refusal"],
)
async def test_openai_failures_surface_as_llm_errors(status: int, body: dict[str, Any]) -> None:
    api = FakeOpenAI(status, body)

    with pytest.raises(LLMError):
        await api.provider().complete_structured(Weather, ASK)


def only_cassette_text(cassette_dir: Path) -> str:
    [cassette] = cassette_dir.glob("*.json")
    return cassette.read_text(encoding="utf-8")


async def test_recorded_cassettes_contain_no_secrets_or_headers(tmp_path: Path) -> None:
    api = FakeOpenAI(200, completion('{"city": "Pune", "celsius": 31}'))

    await RecordingProvider(api.provider(), tmp_path).complete_structured(Weather, ASK)

    assert api.requests[0].headers["authorization"] == f"Bearer {SECRET_KEY}"
    text = only_cassette_text(tmp_path)
    assert SECRET_KEY not in text
    assert "authorization" not in text.lower()
    assert "headers" not in json.loads(text)["request"]


@pytest.mark.parametrize("status", [408, 409, 429, 500, 503])
async def test_retryable_statuses_surface_as_transient_errors(status: int) -> None:
    api = FakeOpenAI(status, {"error": {"message": "try later", "type": "server_error"}})

    with pytest.raises(TransientLLMError):
        await api.provider().complete_structured(Weather, ASK)


@pytest.mark.parametrize("status", [400, 401, 404])
async def test_client_errors_are_permanent(status: int) -> None:
    api = FakeOpenAI(status, {"error": {"message": "no", "type": "invalid_request_error"}})

    with pytest.raises(LLMError) as raised:
        await api.provider().complete_structured(Weather, ASK)

    assert not isinstance(raised.value, TransientLLMError)


async def test_a_dropped_connection_is_transient() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = AsyncOpenAI(
        api_key=SECRET_KEY,
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(refuse)),
    )

    with pytest.raises(TransientLLMError):
        await OpenAIProvider(client, model="gpt-test").complete_structured(Weather, ASK)


async def test_each_answer_reports_its_usage_under_the_configured_model() -> None:
    api = FakeOpenAI(200, completion('{"city": "Pune", "celsius": 31}'))

    with track_usage() as meter:
        await api.provider(model="gpt-4.1-mini").complete_structured(Weather, ASK)

    assert meter.usages == (Usage(model="gpt-4.1-mini", input_tokens=12, output_tokens=8),)


async def test_a_refusal_is_still_billed() -> None:
    api = FakeOpenAI(200, completion(None, refusal="I cannot help with that."))

    with track_usage() as meter, pytest.raises(LLMError):
        await api.provider().complete_structured(Weather, ASK)

    assert [u.output_tokens for u in meter.usages] == [8]


FORECAST = ToolSpec(
    name="get_forecast",
    description="Forecast for a city.",
    input_schema={"type": "object", "properties": {"city": {"type": "string"}}},
)


def tool_completion(content: str | None, calls: list[tuple[str, str, str]]) -> dict[str, Any]:
    body = completion(content)
    message = body["choices"][0]["message"]
    message["tool_calls"] = [
        {"id": id_, "type": "function", "function": {"name": name, "arguments": arguments}}
        for id_, name, arguments in calls
    ]
    body["choices"][0]["finish_reason"] = "tool_calls" if calls else "stop"
    return body


async def test_tool_calls_come_back_as_a_tool_turn_with_parsed_arguments() -> None:
    api = FakeOpenAI(200, tool_completion(None, [("call_1", "get_forecast", '{"city":"Pune"}')]))

    turn = await api.provider().complete_with_tools([FORECAST], ASK)

    assert turn == ToolTurn(
        tool_calls=(ToolCall(id="call_1", name="get_forecast", arguments={"city": "Pune"}),)
    )


async def test_a_tool_request_sends_functions_and_the_tool_round_at_temperature_zero() -> None:
    api = FakeOpenAI(200, tool_completion("It is 31 C.", []))
    call = ToolCall(id="call_1", name="get_forecast", arguments={"city": "Pune"})
    round_ = [
        Message(role="system", content="Use tools."),
        Message(role="user", content="Weather in Pune?"),
        Message(role="assistant", content="", tool_calls=(call,)),
        Message(role="tool", content='{"celsius": 31}', tool_call_id="call_1"),
    ]

    turn = await api.provider(model="gpt-from-env").complete_with_tools([FORECAST], round_)

    assert turn == ToolTurn(text="It is 31 C.")
    sent = json.loads(api.requests[0].content)
    assert sent["model"] == "gpt-from-env"
    assert sent["temperature"] == 0
    assert sent["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "get_forecast",
                "description": "Forecast for a city.",
                "parameters": FORECAST.input_schema,
            },
        }
    ]
    assert sent["messages"][2] == {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "get_forecast", "arguments": '{"city": "Pune"}'},
            }
        ],
    }
    assert sent["messages"][3] == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": '{"celsius": 31}',
    }


async def test_tool_arguments_that_are_not_json_are_an_llm_error() -> None:
    api = FakeOpenAI(200, tool_completion(None, [("call_1", "get_forecast", "{city: Pune")]))

    with pytest.raises(LLMError, match="get_forecast"):
        await api.provider().complete_with_tools([FORECAST], ASK)
