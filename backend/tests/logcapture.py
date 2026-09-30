"""Capture what `configure_logging` writes, and put logging back as it was afterwards."""

import io
import json
import logging
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

import structlog

from promopilot.logs import LogFormat, LogLevel, configure_logging

_TOUCHED = (
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    "anthropic",
    "openai",
    "httpx",
    "httpcore",
)
"""The standard-library loggers `configure_logging` changes, besides the root."""


@contextmanager
def restored_logging() -> Iterator[None]:
    """Whatever `configure_logging` (or `build_app`) does inside is undone on leaving."""
    root = logging.getLogger()
    saved_root = (root.handlers[:], root.level)
    saved = {
        name: (logger.handlers[:], logger.level, logger.propagate, logger.disabled)
        for name in _TOUCHED
        for logger in [logging.getLogger(name)]
    }
    try:
        yield
    finally:
        structlog.reset_defaults()
        root.handlers[:], root.level = saved_root
        for name, (handlers, level_no, propagate, disabled) in saved.items():
            logger = logging.getLogger(name)
            logger.handlers[:] = handlers
            logger.setLevel(level_no)
            logger.propagate, logger.disabled = propagate, disabled


@contextmanager
def captured_logs(
    log_format: LogFormat = "json", *, level: LogLevel = "info", secrets: Sequence[str] = ()
) -> Iterator[io.StringIO]:
    """Everything logged inside, through structlog or the standard library, in the stream."""
    stream = io.StringIO()
    with restored_logging():
        configure_logging(log_format, level=level, secrets=secrets, stream=stream)
        yield stream


def json_lines(stream: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]
