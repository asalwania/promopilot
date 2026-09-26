"""Recorded cassettes: CI and `make demo` replay LLM responses with no key (ADR 0019, ADR 0027).

A cassette is `<cassette_dir>/<request hash>.json`. The hash covers only provider-independent
request content: the schema's JSON Schema (structured calls) or the tool specs (tool calls), the
messages and the temperature. A cassette recorded with one provider or model replays under any
other. Only that content, the parsed response and the usage the call was billed for are
written; transport details such as request headers never reach a cassette. Replay reports the
recorded usage again, so replayed sessions show real token and cost counters.
"""

import hashlib
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from promopilot.llm.provider import (
    STRUCTURED_TEMPERATURE,
    LLMError,
    LLMProvider,
    Message,
    ToolSpec,
    ToolTurn,
)
from promopilot.llm.usage import Usage, UsageMeter, record_usage, track_usage


class CassetteMissError(LLMError):
    """No cassette was recorded for this request (a prompt or schema changed, or never recorded)."""


def _wire(messages: Sequence[Message]) -> list[dict[str, Any]]:
    # Empty tool fields are left out, so plain messages hash exactly as before tool calls existed;
    # provider_state (opaque, provider-specific) never counts.
    return [
        m.model_dump(mode="json", exclude_defaults=True, exclude={"provider_state"})
        for m in messages
    ]


def _structured_content(schema: type[BaseModel], messages: Sequence[Message]) -> dict[str, Any]:
    return {
        "schema": schema.model_json_schema(),
        "messages": _wire(messages),
        "temperature": STRUCTURED_TEMPERATURE,
    }


def _tool_content(tools: Sequence[ToolSpec], messages: Sequence[Message]) -> dict[str, Any]:
    return {
        "tools": [tool.model_dump(mode="json") for tool in tools],
        "messages": _wire(messages),
        "temperature": STRUCTURED_TEMPERATURE,
    }


def _digest(content: dict[str, Any]) -> str:
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def request_hash(schema: type[BaseModel], messages: Sequence[Message]) -> str:
    """A SHA-256 of a structured request's canonical content: identical across processes."""
    return _digest(_structured_content(schema, messages))


def tool_request_hash(tools: Sequence[ToolSpec], messages: Sequence[Message]) -> str:
    """A SHA-256 of a tool request's canonical content; tool-call ids count, provider state not."""
    return _digest(_tool_content(tools, messages))


def _cassette_path(cassette_dir: Path, digest: str) -> Path:
    return cassette_dir / f"{digest}.json"


_CASSETTE_NAME = re.compile(r"[0-9a-f]{64}\.json")


def cassette_paths(cassette_dir: Path) -> list[Path]:
    """The cassettes in `cassette_dir`, ignoring any other file kept next to them."""
    if not cassette_dir.is_dir():
        return []
    return sorted(p for p in cassette_dir.iterdir() if _CASSETTE_NAME.fullmatch(p.name))


class ReplayProvider:
    """Answers from recorded cassettes and raises `CassetteMissError` on any unrecorded request."""

    def __init__(self, cassette_dir: Path) -> None:
        self._dir = cassette_dir

    async def complete_structured[T: BaseModel](
        self, schema: type[T], messages: Sequence[Message]
    ) -> T:
        cassette = self._load(_structured_content(schema, messages), schema.__name__)
        return schema.model_validate(cassette["response"])

    async def complete_with_tools(
        self, tools: Sequence[ToolSpec], messages: Sequence[Message]
    ) -> ToolTurn:
        cassette = self._load(_tool_content(tools, messages), "tool turn")
        return ToolTurn.model_validate(cassette["response"])

    def _load(self, content: dict[str, Any], what: str) -> dict[str, Any]:
        digest = _digest(content)
        path = _cassette_path(self._dir, digest)
        if not path.is_file():
            raise CassetteMissError(
                f"no cassette for request {digest} ({what}) in {self._dir}; "
                "re-record with `make record-cassettes`"
            )
        cassette: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        # Re-report what the recorded call was billed, so replayed sessions show real counters.
        for usage in cassette.get("usage", []):
            record_usage(Usage.model_validate(usage))
        return cassette


class RecordingProvider:
    """Wraps a live provider and writes each request and parsed response as a cassette."""

    def __init__(self, inner: LLMProvider, cassette_dir: Path) -> None:
        self._inner = inner
        self._dir = cassette_dir

    async def complete_structured[T: BaseModel](
        self, schema: type[T], messages: Sequence[Message]
    ) -> T:
        with track_usage() as billed:
            response = await self._inner.complete_structured(schema, messages)
        self._write(_structured_content(schema, messages), schema.__name__, response, billed)
        return response

    async def complete_with_tools(
        self, tools: Sequence[ToolSpec], messages: Sequence[Message]
    ) -> ToolTurn:
        with track_usage() as billed:
            response = await self._inner.complete_with_tools(tools, messages)
        self._write(_tool_content(tools, messages), ToolTurn.__name__, response, billed)
        return response

    def _write(
        self,
        content: dict[str, Any],
        schema_name: str,
        response: BaseModel,
        billed: UsageMeter,
    ) -> None:
        digest = _digest(content)
        cassette = {
            "hash": digest,
            "schema_name": schema_name,
            "request": content,
            "response": response.model_dump(mode="json"),
            # Outside the request, so it never affects the hash (ADR 0027).
            "usage": [usage.model_dump(mode="json") for usage in billed.usages],
        }
        self._dir.mkdir(parents=True, exist_ok=True)
        _cassette_path(self._dir, digest).write_text(
            json.dumps(cassette, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
