from pathlib import Path

import pytest
from pydantic import BaseModel, SecretStr

from promopilot.config import Settings
from promopilot.llm import (
    CassetteMissError,
    FakeProvider,
    Message,
    OpenAIProvider,
    RecordingProvider,
    build_provider,
)


class Weather(BaseModel):
    city: str
    celsius: int


ASK = [Message(role="user", content="Pune, 31")]


async def test_replay_is_the_default_and_reads_the_configured_cassette_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    await RecordingProvider(
        FakeProvider([Weather(city="Pune", celsius=31)]), tmp_path
    ).complete_structured(Weather, ASK)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    settings = Settings(llm_cassette_dir=tmp_path)

    assert settings.llm_provider == "replay"
    assert await build_provider(settings).complete_structured(Weather, ASK) == Weather(
        city="Pune", celsius=31
    )
    with pytest.raises(CassetteMissError, match=str(tmp_path).replace("\\", "\\\\")):
        await build_provider(settings).complete_structured(
            Weather, [Message(role="user", content="?")]
        )


def test_openai_uses_the_key_and_model_from_env() -> None:
    settings = Settings(
        llm_provider="openai", openai_api_key=SecretStr("sk-test"), openai_model="gpt-from-env"
    )

    assert isinstance(build_provider(settings), OpenAIProvider)


@pytest.mark.parametrize(
    ("overrides", "problem"),
    [
        ({"openai_model": "gpt-from-env"}, "OPENAI_API_KEY"),
        ({"openai_api_key": SecretStr("sk-test")}, "OPENAI_MODEL"),
    ],
    ids=["no-key", "no-model"],
)
def test_openai_without_its_config_fails_naming_the_missing_variable(
    overrides: dict[str, object], problem: str
) -> None:
    with pytest.raises(ValueError, match=problem):
        build_provider(Settings(llm_provider="openai", **overrides))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("name", "reason"),
    [("anthropic", "E8"), ("fake", "FakeProvider")],
)
def test_providers_not_buildable_from_env_say_why(name: str, reason: str) -> None:
    with pytest.raises(ValueError, match=reason):
        build_provider(Settings(llm_provider=name))
