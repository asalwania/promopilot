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

from promopilot.llm import LLMError, Message, OpenAIProvider, RecordingProvider

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
