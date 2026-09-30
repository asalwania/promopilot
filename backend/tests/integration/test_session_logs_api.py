"""Safe, traceable logs of planning sessions over HTTP (E11 #71, ADR 0085), with Postgres, a
FakeProvider and the optimising planner on the small world.

- Every line a session request logs, its background run's included, carries the request's id
  (its `X-Request-ID`) and the session's id.
- At info, no brief, amendment, answer, rejection reason or API key appears in the logs; at
  debug, a manager's text appears on debug lines only.
"""

import asyncio
import io
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from testcontainers.community.postgres import PostgresContainer

from promopilot.data import load_dataset
from promopilot.datagen import GeneratedDataset, write
from promopilot.llm import FakeProvider, LLMError
from promopilot.models.demand import DemandModel
from promopilot.models.relations import Relations
from tests.integration.test_sessions_api import (
    BRIEF,
    READING,
    UNBUDGETED,
    Api,
    api_process,
    clarifying_session,
    settled,
)
from tests.logcapture import captured_logs
from tests.logcapture import json_lines as all_lines
from tests.unit.agents.fakes import explainer_down

pytestmark = pytest.mark.integration

MARKER = "Zanzibar-7731"
"""A word no line may show above debug: it is only ever in what the manager wrote."""
KEY = "sk-ant-api03-" + "Kq4" * 14


@pytest.fixture(scope="module")
def postgres_url(
    small_dataset: GeneratedDataset, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[str]:
    data_dir: Path = tmp_path_factory.mktemp("data")
    write(small_dataset, data_dir)
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as postgres:
        url = postgres.get_connection_url()
        asyncio.run(load_dataset(data_dir, url))
        yield url


@pytest.fixture
def running_api(small_models: tuple[DemandModel, Relations]) -> Api:
    return lambda url, llm: api_process(url, llm, small_models)


def app_lines(stream: io.StringIO) -> list[dict[str, Any]]:
    """The app's lines: not the test client's own `httpx` line."""
    return [line for line in all_lines(stream) if line.get("logger") != "httpx"]


async def test_every_line_of_a_session_request_carries_the_request_and_session_ids(
    postgres_url: str, running_api: Api
) -> None:
    async with running_api(
        postgres_url, FakeProvider([UNBUDGETED, READING, explainer_down()])
    ) as client:
        session_id = await clarifying_session(client)
        with captured_logs() as stream:
            answered = await client.post(
                f"/api/sessions/{session_id}/clarify",
                json={"answers": {"marketing_budget": "₹20k"}},
            )
            done = await settled(client, session_id)

    assert answered.status_code == 202, answered.text
    assert done["status"] == "awaiting_approval", done
    lines = app_lines(stream)
    assert lines
    for line in lines:
        assert line["session_id"] == session_id, line
        assert line["request_id"], line
    clarify_id = answered.headers["X-Request-ID"]
    of_clarify = {line["event"] for line in lines if line["request_id"] == clarify_id}
    # The request's own lines, and its background run's: the Explainer fell back to its template.
    assert {"sessions.clarified", "http.request", "explainer_fallback"} <= of_clarify


async def test_at_info_no_brief_or_api_key_appears_in_the_logs(
    postgres_url: str, running_api: Api
) -> None:
    brief = f"{BRIEF}, and keep {MARKER} out of it"
    down = LLMError(f"provider down: key {KEY} [input_value='{brief}', input_type=str]")
    with captured_logs(secrets=[KEY]) as stream:
        async with running_api(postgres_url, FakeProvider([down])) as client:
            created = await client.post("/api/sessions", json={"brief": brief})
            session_id = created.json()["session_id"]
            done = await settled(client, session_id)

    assert done["status"] == "awaiting_clarification", done
    text = stream.getvalue()
    assert MARKER not in text
    assert KEY not in text
    events = {line["event"]: line for line in app_lines(stream)}
    assert events["sessions.created"]["brief_chars"] == len(brief)
    assert events["sessions.created"]["request_id"] == created.headers["X-Request-ID"]
    assert "[REDACTED]" in events["context_fallback"]["error"]


async def test_at_info_no_amendment_or_rejection_reason_appears_in_the_logs(
    postgres_url: str, running_api: Api
) -> None:
    llm = FakeProvider([READING, explainer_down(), READING, explainer_down()])
    with captured_logs() as stream:
        async with running_api(postgres_url, llm) as client:
            session_id = (await client.post("/api/sessions", json={"brief": BRIEF})).json()[
                "session_id"
            ]
            await settled(client, session_id)
            rejected = await client.post(
                f"/api/sessions/{session_id}/reject",
                json={"revision_number": 1, "reason": f"{MARKER} is wrong"},
            )
            amended = await client.post(
                f"/api/sessions/{session_id}/amend", json={"text": f"Drop {MARKER} please"}
            )
            await settled(client, session_id)

    assert (rejected.status_code, amended.status_code) == (200, 202), amended.text
    assert MARKER not in stream.getvalue()
    events = {line["event"]: line for line in app_lines(stream)}
    decided = events["sessions.decided"]
    assert (decided["decision"], decided["revision_number"]) == ("rejected", 1)
    assert events["sessions.amended"]["revision_number"] == 1


async def test_at_debug_a_manager_s_text_appears_on_debug_lines_only(
    postgres_url: str, running_api: Api
) -> None:
    brief = f"{BRIEF}, and keep {MARKER} out of it"
    down = LLMError(f"provider down [input_value='{brief}', input_type=str]")
    with captured_logs(level="debug") as stream:
        async with running_api(postgres_url, FakeProvider([down])) as client:
            session_id = (await client.post("/api/sessions", json={"brief": brief})).json()[
                "session_id"
            ]
            await settled(client, session_id)

    showing = [line for line in app_lines(stream) if MARKER in str(line)]
    assert [line["event"] for line in showing] == ["sessions.brief"]
    assert showing[0]["level"] == "debug"
    assert showing[0]["brief"] == brief
