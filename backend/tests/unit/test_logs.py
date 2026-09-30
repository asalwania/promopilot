"""Structured JSON logs carry the session id (SF-01, #45, ADR 0047): every line logged while a
planning session's graph runs names the session and the node.

Logs are safe (E11 #71, ADR 0085): lines below `LOG_LEVEL` are dropped, secrets are redacted on
every line, and a manager's text (brief, amendment, answers, rejection reason) or an LLM body
appears only on a debug line.
"""

import io
import logging
from collections.abc import Iterator
from uuid import uuid4

import pytest
import structlog
from langgraph.checkpoint.memory import InMemorySaver

from promopilot.agents import GraphTools, build_graph, checkpoint_serializer, start_planning
from promopilot.datagen import GeneratedDataset
from promopilot.llm import FakeProvider, RetryingProvider, TransientLLMError
from promopilot.logs import LogFormat, configure_logging
from tests.logcapture import captured_logs, json_lines
from tests.unit.agents.fakes import InMemoryRetailData, explainer_down
from tests.unit.agents.test_graph import (
    BRIEF,
    POLICY,
    READING,
    RecordedSessions,
    ScriptedPlanner,
    planned,
)

lines = json_lines
log = structlog.get_logger("promopilot.test")

KEY = "sk-ant-api03-" + "Zx9" * 12
PROJECT_KEY = "sk-proj-" + "Q7w" * 10


@pytest.fixture
def logged() -> Iterator[io.StringIO]:
    with captured_logs("json") as stream:
        yield stream


def test_json_logs_are_one_object_per_line_with_level_and_time(logged: io.StringIO) -> None:
    structlog.get_logger("promopilot.test").info("thing.happened", count=3)

    [line] = lines(logged)
    assert line["event"] == "thing.happened"
    assert line["count"] == 3
    assert line["level"] == "info"
    assert "timestamp" in line


def test_console_logs_are_text() -> None:
    with captured_logs("console") as stream:
        structlog.get_logger("promopilot.test").info("thing.happened")

    assert "thing.happened" in stream.getvalue()
    assert not stream.getvalue().startswith("{")


async def test_a_line_logged_inside_a_graph_node_names_the_session_and_node(
    logged: io.StringIO, small_dataset: GeneratedDataset
) -> None:
    async def no_wait(_: float) -> None:
        return None

    llm = RetryingProvider(
        FakeProvider([TransientLLMError("overloaded"), READING, explainer_down()]), sleep=no_wait
    )
    graph = build_graph(
        GraphTools(
            brief_data=InMemoryRetailData(small_dataset),
            planner=ScriptedPlanner(planned()),
            sessions=RecordedSessions(),
            policy=POLICY,
        ),
        llm,
        InMemorySaver(serde=checkpoint_serializer()),
    )
    session_id = uuid4()

    await start_planning(graph, str(session_id), session_id, BRIEF)

    [retry] = [line for line in lines(logged) if line["event"] == "llm_retry"]
    assert retry["session_id"] == str(session_id)
    assert retry["node"] == "context"


def test_lines_below_the_level_are_dropped() -> None:
    with captured_logs(level="warning") as stream:
        log.info("quiet")
        log.warning("loud")

    assert [line["event"] for line in lines(stream)] == ["loud"]


def test_debug_lines_show_at_the_debug_level() -> None:
    with captured_logs(level="debug") as stream:
        log.debug("detail")

    assert [line["event"] for line in lines(stream)] == ["detail"]


@pytest.mark.parametrize(
    "name", ["api_key", "openai_api_key", "password", "Authorization", "token", "x-api-key"]
)
def test_a_secret_named_field_is_redacted(logged: io.StringIO, name: str) -> None:
    log.warning("configured", **{name: "hunter2-hunter2"}, input_tokens=12)

    [line] = lines(logged)
    assert line[name] == "[REDACTED]"
    assert line["input_tokens"] == 12


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        (f"Anthropic failed: invalid key {KEY}", "Anthropic failed: invalid key [REDACTED]"),
        (f"Incorrect API key provided: {PROJECT_KEY}", "Incorrect API key provided: [REDACTED]"),
        ("Incorrect API key provided: sk-proj-****abcd", "Incorrect API key provided: [REDACTED]"),
        ("header Authorization: Bearer abc.def-ghi", "header Authorization: Bearer [REDACTED]"),
        ('{"x-api-key": "abc123def"}', '{"x-api-key": "[REDACTED]"}'),
        (
            "cannot reach postgresql+asyncpg://promopilot:s3cret@db:5432/promopilot",
            "cannot reach postgresql+asyncpg://promopilot:[REDACTED]@db:5432/promopilot",
        ),
        ("the task-abcdefghij finished", "the task-abcdefghij finished"),
    ],
)
def test_a_secret_inside_any_text_is_redacted(logged: io.StringIO, text: str, shown: str) -> None:
    log.warning(text, error=text, nested={"errors": [text]})

    [line] = lines(logged)
    assert line["event"] == shown
    assert line["error"] == shown
    assert line["nested"] == {"errors": [shown]}


def test_a_configured_key_is_redacted_wherever_it_appears() -> None:
    odd_key = "live-key-without-a-known-prefix-123"
    with captured_logs(secrets=[odd_key, ""]) as stream:
        log.warning("llm_retry", error=f"rejected {odd_key}")

    [line] = lines(stream)
    assert odd_key not in stream.getvalue()
    assert line["error"] == "rejected [REDACTED]"


@pytest.mark.parametrize("log_format", ["json", "console"])
def test_an_exception_s_text_and_traceback_are_redacted(log_format: LogFormat) -> None:
    with captured_logs(log_format) as stream:
        try:
            raise RuntimeError(f"connect failed with {KEY}")
        except RuntimeError:
            log.exception("sessions.planning_failed")

    assert "sessions.planning_failed" in stream.getvalue()
    assert "RuntimeError" in stream.getvalue()
    assert KEY not in stream.getvalue()


@pytest.mark.parametrize("field", ["brief", "amendment", "answers", "rejection_reason", "messages"])
@pytest.mark.parametrize("level", ["info", "warning", "error"])
def test_a_manager_s_text_is_withheld_above_debug(field: str, level: str) -> None:
    text = "Clear the winter jackets in the North before the monsoon sale"
    with captured_logs(level="debug") as stream:
        getattr(log, level)("sessions.something", **{field: text})

    [line] = lines(stream)
    assert text not in stream.getvalue()
    assert line[field] == f"[withheld: {len(text)} chars]"


def test_a_manager_s_text_shows_on_a_debug_line() -> None:
    text = "Clear the winter jackets in the North"
    with captured_logs(level="debug") as stream:
        log.debug("sessions.brief", brief=text, answers={"q1": "yes"})

    [line] = lines(stream)
    assert line["brief"] == text
    assert line["answers"] == {"q1": "yes"}


def test_an_llm_answer_quoted_in_an_error_is_cut_above_debug(logged: io.StringIO) -> None:
    error = (
        "Anthropic m failed on BriefReading: 1 validation error for BriefReading\n"
        "objective\n  Input should be 'profit' [type=literal_error, "
        "input_value='clear the NorthJackets brief, please', input_type=str]\n"
        "    For further information visit https://errors.pydantic.dev/2/v/literal_error"
    )
    log.warning("context_fallback", error=error)

    [line] = lines(logged)
    assert "NorthJackets" not in logged.getvalue()
    assert "input_value=[withheld], input_type=str" in line["error"]
    assert "literal_error" in line["error"]


def test_an_llm_answer_quoted_in_an_error_shows_on_a_debug_line() -> None:
    with captured_logs(level="debug") as stream:
        log.debug("llm.detail", error="[type=x, input_value='NorthJackets', input_type=str]")

    assert "NorthJackets" in stream.getvalue()


def test_standard_library_lines_are_json_with_the_bound_ids_and_redacted(
    logged: io.StringIO,
) -> None:
    with structlog.contextvars.bound_contextvars(request_id="r-1", session_id="s-1"):
        logging.getLogger("uvicorn.error").warning("upstream said %s", KEY)

    [line] = lines(logged)
    assert line["event"] == "upstream said [REDACTED]"
    assert line["level"] == "warning"
    assert line["logger"] == "uvicorn.error"
    assert (line["request_id"], line["session_id"]) == ("r-1", "s-1")
    assert "timestamp" in line


def test_standard_library_lines_follow_the_level() -> None:
    with captured_logs(level="warning") as stream:
        logging.getLogger("langgraph").info("quiet")
        logging.getLogger("langgraph").error("loud")

    assert [line["event"] for line in lines(stream)] == ["loud"]


def test_uvicorn_s_access_line_is_left_to_the_api_s_own() -> None:
    with captured_logs(level="debug") as stream:
        logging.getLogger("uvicorn.access").info('127.0.0.1 - "GET /api/health HTTP/1.1" 200')

    assert stream.getvalue() == ""


def test_the_llm_sdks_never_log_their_request_bodies_even_at_debug() -> None:
    with captured_logs(level="debug") as stream:
        for name in ("anthropic._base_client", "openai._base_client", "httpx", "httpcore.http11"):
            logging.getLogger(name).debug("Request options: {'json_data': {'messages': []}}")
        logging.getLogger("httpx").info("HTTP Request: POST https://api.example/v1 200")

    assert [line["event"] for line in lines(stream)] == [
        "HTTP Request: POST https://api.example/v1 200"
    ]


def test_configuring_twice_writes_each_standard_library_line_once() -> None:
    with captured_logs() as first:
        stream = io.StringIO()
        configure_logging("json", stream=stream)
        logging.getLogger("langgraph").warning("once")

    assert first.getvalue() == ""
    assert [line["event"] for line in lines(stream)] == ["once"]
