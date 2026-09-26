"""LLM layer: one `LLMProvider` protocol, with fake, replay and OpenAI providers."""

from promopilot.llm.anthropic_provider import AnthropicProvider
from promopilot.llm.factory import build_provider
from promopilot.llm.fake import FakeCall, FakeProvider
from promopilot.llm.openai_provider import OpenAIProvider
from promopilot.llm.provider import (
    LLMError,
    LLMProvider,
    Message,
    ToolCall,
    ToolSpec,
    ToolTurn,
    TransientLLMError,
)
from promopilot.llm.replay import (
    CassetteMissError,
    RecordingProvider,
    ReplayProvider,
    cassette_paths,
    request_hash,
    tool_request_hash,
)
from promopilot.llm.resilience import FallbackProvider, RetryingProvider
from promopilot.llm.usage import Usage, UsageMeter, UsageTotals, record_usage, track_usage

__all__ = [
    "AnthropicProvider",
    "CassetteMissError",
    "FakeCall",
    "FakeProvider",
    "FallbackProvider",
    "LLMError",
    "LLMProvider",
    "Message",
    "OpenAIProvider",
    "RecordingProvider",
    "ReplayProvider",
    "RetryingProvider",
    "ToolCall",
    "ToolSpec",
    "ToolTurn",
    "TransientLLMError",
    "Usage",
    "UsageMeter",
    "UsageTotals",
    "build_provider",
    "cassette_paths",
    "record_usage",
    "request_hash",
    "tool_request_hash",
    "track_usage",
]
