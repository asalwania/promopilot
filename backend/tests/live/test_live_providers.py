"""Live smoke checks against the real providers: marked `live`, excluded from every default run.

Run deliberately with keys exported: `uv run pytest -m live tests/live`. Each makes one small
paid call per provider; CI never runs them.
"""

from typing import Literal

import pytest
from pydantic import BaseModel

from promopilot.config import Settings
from promopilot.llm import Message, ToolSpec, build_provider, track_usage

pytestmark = pytest.mark.live


class City(BaseModel):
    city: str


ASK = [Message(role="user", content="Name the city in: 'Monsoon sale in Pune'. Answer as JSON.")]
FORECAST = ToolSpec(
    name="get_forecast",
    description="Get the weather forecast for a city.",
    input_schema={
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"],
    },
)


def live(provider: Literal["openai", "anthropic"]) -> Settings:
    settings = Settings(llm_provider=provider)
    key = settings.openai_api_key if provider == "openai" else settings.anthropic_api_key
    if key is None:
        pytest.skip(f"no {provider.upper()}_API_KEY in the environment")
    return settings


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
async def test_live_structured_and_tool_calls_answer_and_are_billed(
    provider: Literal["openai", "anthropic"],
) -> None:
    llm = build_provider(live(provider))

    with track_usage() as meter:
        city = await llm.complete_structured(City, ASK)
        turn = await llm.complete_with_tools(
            [FORECAST], [Message(role="user", content="What is the weather in Pune?")]
        )

    assert city.city == "Pune"
    assert [call.name for call in turn.tool_calls] == ["get_forecast"]
    assert all(usage.input_tokens > 0 for usage in meter.usages)
