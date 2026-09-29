from pathlib import Path

import pytest
from pydantic import BaseModel, SecretStr
from structlog.testing import capture_logs

from promopilot.config import Settings
from promopilot.llm import (
    CassetteMissError,
    FakeProvider,
    FallbackProvider,
    Message,
    RecordingProvider,
    ReplayProvider,
    RetryingProvider,
    build_provider,
)


@pytest.fixture(autouse=True)
def no_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings read the environment: keep a developer's real keys out of these tests."""
    for name in ("OPENAI_API_KEY", "OPENAI_MODEL", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL"):
        monkeypatch.delenv(name, raising=False)


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


OPENAI = {"openai_api_key": SecretStr("sk-test"), "openai_model": "gpt-4.1-mini"}
ANTHROPIC = {"anthropic_api_key": SecretStr("sk-ant-test"), "anthropic_model": "claude-sonnet-5"}


@pytest.mark.parametrize("primary", ["openai", "anthropic"])
def test_a_live_provider_alone_is_retried_and_warns_that_there_is_no_fallback(
    primary: str,
) -> None:
    config = OPENAI if primary == "openai" else ANTHROPIC

    with capture_logs() as logs:
        llm = build_provider(Settings(llm_provider=primary, **config))  # type: ignore[arg-type]

    assert isinstance(llm, RetryingProvider)
    assert [log["event"] for log in logs] == ["llm_no_fallback"]


@pytest.mark.parametrize("primary", ["openai", "anthropic"])
def test_with_both_keys_the_other_live_provider_is_the_fallback(primary: str) -> None:
    settings = Settings(llm_provider=primary, **OPENAI, **ANTHROPIC)  # type: ignore[arg-type]

    assert isinstance(build_provider(settings), FallbackProvider)


def test_replay_never_falls_back_even_with_live_keys(tmp_path: Path) -> None:
    settings = Settings(llm_provider="replay", llm_cassette_dir=tmp_path, **OPENAI, **ANTHROPIC)  # type: ignore[arg-type]

    assert isinstance(build_provider(settings), ReplayProvider)


@pytest.mark.parametrize(
    ("provider", "overrides", "problem"),
    [
        ("openai", {"openai_model": "gpt-from-env"}, "OPENAI_API_KEY"),
        ("openai", {"openai_api_key": SecretStr("sk-test")}, "OPENAI_MODEL"),
        ("anthropic", {"anthropic_model": "claude-sonnet-5"}, "ANTHROPIC_API_KEY"),
        ("anthropic", {"anthropic_api_key": SecretStr("sk-ant-test")}, "ANTHROPIC_MODEL"),
    ],
    ids=["openai-no-key", "openai-no-model", "anthropic-no-key", "anthropic-no-model"],
)
def test_a_primary_without_its_config_fails_naming_the_missing_variable(
    provider: str, overrides: dict[str, object], problem: str
) -> None:
    with pytest.raises(ValueError, match=problem):
        build_provider(Settings(llm_provider=provider, **overrides))  # type: ignore[arg-type]


def test_fake_is_not_buildable_from_env() -> None:
    with pytest.raises(ValueError, match="FakeProvider"):
        build_provider(Settings(llm_provider="fake"))


def test_an_empty_key_from_an_env_file_counts_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-5")

    with capture_logs() as logs:
        llm = build_provider(Settings(llm_provider="openai", **OPENAI))  # type: ignore[arg-type]

    assert isinstance(llm, RetryingProvider)
    assert [log["event"] for log in logs] == ["llm_no_fallback"]
    monkeypatch.setenv("OPENAI_API_KEY", "")
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        build_provider(Settings(llm_provider="openai", openai_model="gpt-4.1-mini"))


@pytest.mark.parametrize("primary", ["openai", "anthropic"])
def test_a_live_provider_times_out_each_attempt_after_the_configured_seconds(
    primary: str,
) -> None:
    config = OPENAI if primary == "openai" else ANTHROPIC

    llm = build_provider(Settings(llm_provider=primary, llm_timeout_seconds=12.5, **config))  # type: ignore[arg-type]

    assert isinstance(llm, RetryingProvider)
    assert llm.timeout_s == 12.5
