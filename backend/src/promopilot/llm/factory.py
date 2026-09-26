"""Choose the provider named by `LLM_PROVIDER` (ADR 0001)."""

import openai

from promopilot.config import Settings
from promopilot.llm.openai_provider import OpenAIProvider
from promopilot.llm.provider import LLMProvider
from promopilot.llm.replay import ReplayProvider


def build_provider(settings: Settings) -> LLMProvider:
    match settings.llm_provider:
        case "replay":
            return ReplayProvider(settings.llm_cassette_dir)
        case "openai":
            if settings.openai_api_key is None:
                raise ValueError("LLM_PROVIDER=openai needs OPENAI_API_KEY")
            if not settings.openai_model:
                raise ValueError("LLM_PROVIDER=openai needs OPENAI_MODEL")
            client = openai.AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value())
            return OpenAIProvider(client, model=settings.openai_model)
        case "anthropic":
            raise ValueError("LLM_PROVIDER=anthropic arrives in E8 (provider fallback)")
        case "fake":
            raise ValueError("LLM_PROVIDER=fake is scripted: construct FakeProvider in tests")
