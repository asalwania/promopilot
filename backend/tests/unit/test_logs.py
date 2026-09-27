"""Structured JSON logs carry the session id (SF-01, #45, ADR 0047): every line logged while a
planning session's graph runs names the session and the node."""

import io
import json
from collections.abc import Iterator
from uuid import uuid4

import pytest
import structlog
from langgraph.checkpoint.memory import InMemorySaver

from promopilot.agents import GraphTools, build_graph, checkpoint_serializer, start_planning
from promopilot.datagen import GeneratedDataset
from promopilot.llm import FakeProvider, RetryingProvider, TransientLLMError
from promopilot.logs import configure_logging
from tests.unit.agents.fakes import InMemoryRetailData
from tests.unit.agents.test_graph import (
    BRIEF,
    POLICY,
    READING,
    RecordedSessions,
    ScriptedPlanner,
    planned,
)


@pytest.fixture
def logged() -> Iterator[io.StringIO]:
    stream = io.StringIO()
    configure_logging("json", stream=stream)
    yield stream
    structlog.reset_defaults()


def lines(stream: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_json_logs_are_one_object_per_line_with_level_and_time(logged: io.StringIO) -> None:
    structlog.get_logger("promopilot.test").info("thing.happened", count=3)

    [line] = lines(logged)
    assert line["event"] == "thing.happened"
    assert line["count"] == 3
    assert line["level"] == "info"
    assert "timestamp" in line


def test_console_logs_are_text(logged: io.StringIO) -> None:
    stream = io.StringIO()
    configure_logging("console", stream=stream)

    structlog.get_logger("promopilot.test").info("thing.happened")

    assert "thing.happened" in stream.getvalue()
    assert not stream.getvalue().startswith("{")


async def test_a_line_logged_inside_a_graph_node_names_the_session_and_node(
    logged: io.StringIO, small_dataset: GeneratedDataset
) -> None:
    async def no_wait(_: float) -> None:
        return None

    llm = RetryingProvider(FakeProvider([TransientLLMError("overloaded"), READING]), sleep=no_wait)
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
