"""Structured, safe logging (SF-01, ADR 0047, ADR 0085): one JSON object per line, or readable
text for development (`LOG_FORMAT=console`), at `LOG_LEVEL` and above.

Values bound with `structlog.contextvars` join every line logged in that context. The API's
request guard binds the request id; a session's route, its background run and each traced
graph node bind the session id (and the node), so every line says which request and session it
came from.

Every line, from structlog or the standard library (uvicorn, httpx, LangGraph, ...), passes the
same two guards before it is rendered:

- **A manager's text only at debug.** A brief, amendment, clarification answers, a rejection
  reason or an LLM body (`MANAGER_TEXT` fields) is replaced by its length on any line above
  debug, and so is an `input_value=...` that a validation error quotes (an LLM answer can echo
  the brief).
- **Secrets never.** A secret-named field (`api_key`, `password`, `token`, ...) is `[REDACTED]`,
  and so is any API key (`sk-...`, a `Bearer` token, an `x-api-key` value, the configured keys)
  or URL password inside any text, tracebacks included.
"""

import logging
import re
import sys
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Final, Literal, TextIO

import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

type LogFormat = Literal["json", "console"]
type LogLevel = Literal["debug", "info", "warning", "error"]

REDACTED: Final = "[REDACTED]"
MANAGER_TEXT: Final = frozenset(
    {"brief", "amendment", "answers", "rejection_reason", "messages", "prompt", "completion"}
)
"""Fields that hold what a manager wrote, or what went to or came from an LLM: debug only."""

_SECRET_NAME: Final = re.compile(
    r"(^|[_-])(api[_-]?key|password|passwd|secret|token|authorization|cookie)$", re.IGNORECASE
)
_SECRET_TEXT: Final = (
    # OpenAI (`sk-`, `sk-proj-`) and Anthropic (`sk-ant-`) keys, masked ones included.
    (re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_*\-]{8,}"), REDACTED),
    (re.compile(r"(\bBearer\s+)[A-Za-z0-9._~+/=\-]+", re.IGNORECASE), rf"\1{REDACTED}"),
    (re.compile(r"""(x-api-key["']?\s*[:=]\s*["']?)[^\s"',}]+""", re.IGNORECASE), rf"\1{REDACTED}"),
    # The password of a URL's user info: `scheme://user:password@host`.
    (re.compile(r"([a-z][a-z0-9+.\-]*://[^:/@\s]+:)[^@\s/]+@", re.IGNORECASE), rf"\1{REDACTED}@"),
)
_QUOTED_INPUT: Final = re.compile(r"input_value=(?:.*?(?=, input_type=)|[^\n]*)", re.DOTALL)
_MIN_SECRET_CHARS: Final = 8

_ACCESS_LOGGER: Final = "uvicorn.access"
"""Uvicorn's access line; the API logs its own `http.request` line instead (ADR 0085)."""
_UVICORN_LOGGERS: Final = ("uvicorn", "uvicorn.error")
_BODY_LOGGERS: Final = ("anthropic", "openai", "httpx", "httpcore")
"""Their debug lines hold whole LLM requests and responses, so they never log below info."""


def configure_logging(
    log_format: LogFormat,
    *,
    level: LogLevel = "info",
    secrets: Iterable[str] = (),
    stream: TextIO | None = None,
) -> None:
    """Log to `stream` (standard output by default) in `log_format`, at `level` and above,
    with `secrets` (the configured API keys) redacted wherever they appear."""
    level_no = logging.getLevelNamesMapping()[level.upper()]
    output = stream or sys.stdout
    known = tuple(secret for secret in secrets if len(secret) >= _MIN_SECRET_CHARS)
    renderer: Processor = (
        structlog.processors.JSONRenderer()
        if log_format == "json"
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    safe: list[Processor] = [
        structlog.processors.format_exc_info,
        _withhold_manager_text,
        _Redact(known),
    ]
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            *safe,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level_no),
        logger_factory=structlog.PrintLoggerFactory(file=output),
        cache_logger_on_first_use=False,
    )
    _route_standard_library(output, level_no, safe, renderer)


def _route_standard_library(
    stream: TextIO, level_no: int, safe: list[Processor], renderer: Processor
) -> None:
    """Send the standard library's lines through the same chain, to the same stream."""
    handler = logging.StreamHandler(stream)
    handler.set_name(__name__)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=[
                structlog.contextvars.merge_contextvars,
                structlog.stdlib.add_log_level,
                structlog.stdlib.add_logger_name,
                structlog.processors.TimeStamper(fmt="iso", utc=True),
            ],
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                *safe,
                renderer,
            ],
        )
    )
    root = logging.getLogger()
    root.handlers[:] = [h for h in root.handlers if h.get_name() != __name__]
    root.addHandler(handler)
    root.setLevel(level_no)
    for name in _UVICORN_LOGGERS:
        uvicorn = logging.getLogger(name)
        uvicorn.handlers.clear()
        uvicorn.propagate = True
        uvicorn.setLevel(logging.NOTSET)
    access = logging.getLogger(_ACCESS_LOGGER)
    access.handlers.clear()
    access.propagate = False
    access.disabled = True
    for name in _BODY_LOGGERS:
        logging.getLogger(name).setLevel(max(level_no, logging.INFO))


def _withhold_manager_text(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    if event_dict.get("level") == "debug":
        return event_dict
    for key, value in event_dict.items():
        if key in MANAGER_TEXT:
            event_dict[key] = (
                f"[withheld: {len(value)} chars]" if isinstance(value, str) else "[withheld]"
            )
        else:
            event_dict[key] = _each_text(value, _cut_quoted_input)
    return event_dict


def _cut_quoted_input(text: str) -> str:
    return _QUOTED_INPUT.sub("input_value=[withheld]", text) if "input_value=" in text else text


class _Redact:
    """Blanks secret-named fields, and API keys and URL passwords inside any text."""

    def __init__(self, known: tuple[str, ...]) -> None:
        self._known = known

    def __call__(self, _: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
        for key, value in event_dict.items():
            event_dict[key] = REDACTED if _is_secret_name(key) else _each_text(value, self._text)
        return event_dict

    def _text(self, text: str) -> str:
        for secret in self._known:
            text = text.replace(secret, REDACTED)
        for pattern, replacement in _SECRET_TEXT:
            text = pattern.sub(replacement, text)
        return text


def _is_secret_name(key: object) -> bool:
    return isinstance(key, str) and _SECRET_NAME.search(key) is not None


def _each_text(value: Any, change: Callable[[str], str]) -> Any:
    """`value` with `change` applied to every string in it, through dicts, lists and tuples;
    a secret-named key's value inside is blanked."""
    if isinstance(value, str):
        return change(value)
    if isinstance(value, Mapping):
        return {
            key: REDACTED if _is_secret_name(key) else _each_text(item, change)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        items = [_each_text(item, change) for item in value]
        return tuple(items) if isinstance(value, tuple) else items
    return value
