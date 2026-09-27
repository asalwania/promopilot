"""Structured logging (SF-01, ADR 0047): one JSON object per line, or readable text for
development (`LOG_FORMAT=console`).

Values bound with `structlog.contextvars` join every line logged in that context: a planning
session's graph run binds the session id, and each traced node its name, so every line logged
while a session plans says which session and node it came from. Request ids, redaction and
brief handling are E11's (#71).
"""

import sys
from typing import Literal, TextIO

import structlog

type LogFormat = Literal["json", "console"]


def configure_logging(log_format: LogFormat, *, stream: TextIO | None = None) -> None:
    """Log to `stream` (standard output by default) in `log_format`."""
    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer()
        if log_format == "json"
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            *([structlog.processors.format_exc_info] if log_format == "json" else []),
            renderer,
        ],
        logger_factory=structlog.PrintLoggerFactory(file=stream or sys.stdout),
        cache_logger_on_first_use=False,
    )
