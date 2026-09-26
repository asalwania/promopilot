"""Recorded cassettes: CI and `make demo` replay LLM responses with no key (ADR 0019).

A cassette is `<cassette_dir>/<request hash>.json`. The hash covers only provider-independent
request content (the schema's JSON Schema, the messages and the temperature), so a cassette
recorded with one provider or model replays under any other. Only that content and the parsed
response are written; transport details such as request headers never reach a cassette.
"""

import hashlib
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from promopilot.llm.provider import STRUCTURED_TEMPERATURE, LLMError, LLMProvider, Message


class CassetteMissError(LLMError):
    """No cassette was recorded for this request (a prompt or schema changed, or never recorded)."""


def _request_content(schema: type[BaseModel], messages: Sequence[Message]) -> dict[str, Any]:
    return {
        "schema": schema.model_json_schema(),
        "messages": [message.model_dump() for message in messages],
        "temperature": STRUCTURED_TEMPERATURE,
    }


def request_hash(schema: type[BaseModel], messages: Sequence[Message]) -> str:
    """A SHA-256 of the canonical request content: identical across processes and machines."""
    canonical = json.dumps(
        _request_content(schema, messages), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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
        digest = request_hash(schema, messages)
        path = _cassette_path(self._dir, digest)
        if not path.is_file():
            raise CassetteMissError(
                f"no cassette for request {digest} ({schema.__name__}) in {self._dir}; "
                "re-record with `make record-cassettes`"
            )
        cassette = json.loads(path.read_text(encoding="utf-8"))
        return schema.model_validate(cassette["response"])


class RecordingProvider:
    """Wraps a live provider and writes each request and parsed response as a cassette."""

    def __init__(self, inner: LLMProvider, cassette_dir: Path) -> None:
        self._inner = inner
        self._dir = cassette_dir

    async def complete_structured[T: BaseModel](
        self, schema: type[T], messages: Sequence[Message]
    ) -> T:
        response = await self._inner.complete_structured(schema, messages)
        digest = request_hash(schema, messages)
        cassette = {
            "hash": digest,
            "schema_name": schema.__name__,
            "request": _request_content(schema, messages),
            "response": response.model_dump(mode="json"),
        }
        self._dir.mkdir(parents=True, exist_ok=True)
        _cassette_path(self._dir, digest).write_text(
            json.dumps(cassette, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return response
