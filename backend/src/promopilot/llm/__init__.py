"""LLM layer: one `LLMProvider` protocol, with fake, replay and OpenAI providers."""

from promopilot.llm.factory import build_provider
from promopilot.llm.fake import FakeCall, FakeProvider
from promopilot.llm.openai_provider import OpenAIProvider
from promopilot.llm.provider import LLMError, LLMProvider, Message
from promopilot.llm.replay import (
    CassetteMissError,
    RecordingProvider,
    ReplayProvider,
    request_hash,
)

__all__ = [
    "CassetteMissError",
    "FakeCall",
    "FakeProvider",
    "LLMError",
    "LLMProvider",
    "Message",
    "OpenAIProvider",
    "RecordingProvider",
    "ReplayProvider",
    "build_provider",
    "request_hash",
]
