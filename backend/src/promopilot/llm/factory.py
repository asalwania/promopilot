"""Choose the provider named by `LLM_PROVIDER` (ADR 0001) and make it resilient (ADR 0027).

A live primary is wrapped in `RetryingProvider`. When the other live provider's key and model
are also set, it becomes the retried secondary behind a `FallbackProvider`; otherwise a
warning says there is no fallback. Replay never falls back: a cassette miss must fail loudly.
SDK clients are built with `max_retries=0` so retries happen only in `RetryingProvider`, and
with `LLM_TIMEOUT_SECONDS`, which `RetryingProvider` also enforces on every attempt (ADR 0071).
"""

from typing import Literal

import anthropic
import openai
import structlog

from promopilot.config import Settings
from promopilot.llm.anthropic_provider import AnthropicProvider
from promopilot.llm.openai_provider import OpenAIProvider
from promopilot.llm.provider import LLMProvider
from promopilot.llm.replay import ReplayProvider
from promopilot.llm.resilience import FallbackProvider, RetryingProvider

log = structlog.get_logger(__name__)

Live = Literal["openai", "anthropic"]


def build_provider(settings: Settings) -> LLMProvider:
    match settings.llm_provider:
        case "replay":
            return ReplayProvider(settings.llm_cassette_dir)
        case "openai" | "anthropic" as primary:
            return _resilient(primary, settings)
        case "fake":
            raise ValueError("LLM_PROVIDER=fake is scripted: construct FakeProvider in tests")


def _resilient(primary: Live, settings: Settings) -> LLMProvider:
    first = _retrying(_live(primary, settings), settings)
    secondary: Live = "anthropic" if primary == "openai" else "openai"
    if not _configured(secondary, settings):
        log.warning("llm_no_fallback", primary=primary, missing=secondary)
        return first
    return FallbackProvider(first, _retrying(_live(secondary, settings), settings))


def _retrying(provider: LLMProvider, settings: Settings) -> RetryingProvider:
    return RetryingProvider(provider, timeout_s=settings.llm_timeout_seconds)


def _credentials(name: Live, settings: Settings) -> tuple[str, str | None]:
    """The key and model for `name`; an empty key (e.g. `KEY=` in an env file) is no key."""
    if name == "openai":
        secret, model = settings.openai_api_key, settings.openai_model
    else:
        secret, model = settings.anthropic_api_key, settings.anthropic_model
    return (secret.get_secret_value() if secret is not None else ""), (model or None)


def _configured(name: Live, settings: Settings) -> bool:
    key, model = _credentials(name, settings)
    return bool(key) and model is not None


def _live(name: Live, settings: Settings) -> LLMProvider:
    key, model = _credentials(name, settings)
    variable = name.upper()
    if not key:
        raise ValueError(f"LLM_PROVIDER={name} needs {variable}_API_KEY")
    if model is None:
        raise ValueError(f"LLM_PROVIDER={name} needs {variable}_MODEL")
    timeout = settings.llm_timeout_seconds
    if name == "openai":
        client = openai.AsyncOpenAI(api_key=key, max_retries=0, timeout=timeout)
        return OpenAIProvider(client, model=model)
    return AnthropicProvider(
        anthropic.AsyncAnthropic(api_key=key, max_retries=0, timeout=timeout), model=model
    )
