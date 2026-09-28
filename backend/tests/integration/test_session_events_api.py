"""The live trace over SSE (SF-01, #45, ADR 0047): `GET /api/sessions/{id}/events` streams a
session's trace events in order, resumes after `Last-Event-ID` without gaps or duplicates,
ends once the session is final, and its token-usage events add up to the session's usage."""

import asyncio
import json
import socket
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from fastapi import FastAPI
from httpx import AsyncClient
from testcontainers.community.postgres import PostgresContainer

from promopilot.data import load_dataset
from promopilot.datagen import GeneratedDataset, write
from promopilot.llm import FakeProvider, Usage
from promopilot.models.demand import DemandModel
from promopilot.models.relations import Relations
from tests.integration.test_sessions_api import (
    BRIEF,
    READING,
    GatedProvider,
    api_app,
    api_process,
    settled,
)
from tests.unit.agents.billed import BilledProvider
from tests.unit.agents.fakes import explainer_down

pytestmark = pytest.mark.integration


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


def sse(text: str) -> list[dict[str, str]]:
    """The events of an SSE body, each as its fields; comments (keepalives) are skipped."""
    events = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        fields: dict[str, str] = {}
        for line in block.split("\n"):
            if not line or line.startswith(":"):
                continue
            name, _, value = line.partition(":")
            fields[name] = value.removeprefix(" ")
        if fields:
            events.append(fields)
    return events


def trace_of(events: list[dict[str, str]]) -> list[dict[str, Any]]:
    """The trace events of a stream, without its closing `end` event."""
    return [json.loads(event["data"]) for event in events if "event" not in event]


async def approved_session(client: AsyncClient) -> str:
    session_id: str = (await client.post("/api/sessions", json={"brief": BRIEF})).json()[
        "session_id"
    ]
    assert (await settled(client, session_id))["status"] == "awaiting_approval"
    approved = await client.post(f"/api/sessions/{session_id}/approve", json={"revision_number": 1})
    assert approved.status_code == 200
    return session_id


async def test_the_stream_sends_every_event_in_order_then_ends_once_approved(
    postgres_url: str, small_models: tuple[DemandModel, Relations]
) -> None:
    async with api_process(
        postgres_url, FakeProvider([READING, explainer_down()]), small_models
    ) as client:
        session_id = await approved_session(client)
        response = await client.get(f"/api/sessions/{session_id}/events")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    events = sse(response.text)
    trace = trace_of(events)
    assert [event["id"] for event in events[:-1]] == [str(n) for n in range(1, len(trace) + 1)]
    assert [event["id"] for event in trace] == list(range(1, len(trace) + 1))
    assert {event["session_id"] for event in trace} == {session_id}
    assert [(e["node"], e["payload"]["kind"]) for e in trace][:2] == [
        ("context", "node_started"),
        ("context", "node_finished"),
    ]
    nodes = [e["node"] for e in trace if e["payload"]["kind"] == "node_started"]
    assert nodes == ["context", "planner", "critic", "explainer", "approval", "approval", "done"]
    assert trace[-1]["node"] == "done"
    assert trace[-1]["payload"]["outcome"] == "completed"
    decisions = [e["payload"]["decision"] for e in trace if e["payload"]["kind"] == "decision"]
    assert decisions == ["plan_valid", "explainer_fallback", "approved"]
    end = events[-1]
    assert end["event"] == "end"
    assert "id" not in end
    assert json.loads(end["data"]) == {"session_id": session_id, "status": "approved"}


async def test_the_stream_resumes_after_last_event_id_without_gaps_or_duplicates(
    postgres_url: str, small_models: tuple[DemandModel, Relations]
) -> None:
    async with api_process(
        postgres_url, FakeProvider([READING, explainer_down()]), small_models
    ) as client:
        session_id = await approved_session(client)
        url = f"/api/sessions/{session_id}/events"
        full = trace_of(sse((await client.get(url)).text))
        last = len(full)
        resumed = {
            after: trace_of(
                sse((await client.get(url, headers={"Last-Event-ID": str(after)})).text)
            )
            for after in (1, 4, last - 1, last)
        }
        garbled = trace_of(sse((await client.get(url, headers={"Last-Event-ID": "x"})).text))

    for after, events in resumed.items():
        assert events == full[after:], f"after {after}"
    assert garbled == full


async def test_a_failed_session_streams_its_trace_then_ends(
    postgres_url: str, small_models: tuple[DemandModel, Relations]
) -> None:
    unbudgeted = READING.model_copy(update={"marketing_budget": None})
    async with api_process(postgres_url, FakeProvider([unbudgeted]), small_models) as client:
        session_id = (await client.post("/api/sessions", json={"brief": BRIEF})).json()[
            "session_id"
        ]
        assert (await settled(client, session_id))["status"] == "failed"
        events = sse((await client.get(f"/api/sessions/{session_id}/events")).text)

    trace = trace_of(events)
    assert [(e["node"], e["payload"]["kind"]) for e in trace] == [
        ("context", "node_started"),
        ("context", "node_finished"),
    ]
    assert trace[-1]["payload"]["outcome"] == "failed"
    assert "marketing budget" in trace[-1]["payload"]["error"]
    assert json.loads(events[-1]["data"])["status"] == "failed"


async def test_an_unknown_sessions_stream_is_404(postgres_url: str) -> None:
    async with api_process(postgres_url, FakeProvider([]), None) as client:
        response = await client.get("/api/sessions/00000000-0000-0000-0000-000000000000/events")

    assert response.status_code == 404


async def test_token_usage_events_add_up_to_the_sessions_usage(
    postgres_url: str, small_models: tuple[DemandModel, Relations]
) -> None:
    llm = BilledProvider(
        FakeProvider([READING, explainer_down()]),
        [
            Usage(model="gpt-4.1-mini", input_tokens=1_234, output_tokens=321),
            Usage(model="gpt-4.1-mini", input_tokens=766, output_tokens=0),
        ],
    )
    async with api_process(postgres_url, llm, small_models) as client:
        session_id = await approved_session(client)
        session = (await client.get(f"/api/sessions/{session_id}")).json()
        trace = trace_of(sse((await client.get(f"/api/sessions/{session_id}/events")).text))

    used = [e["payload"] for e in trace if e["payload"]["kind"] == "token_usage"]
    assert len(used) == 2  # the Context's call and the Explainer's billed failure
    usage = session["usage"]
    assert usage["calls"] == len(used)
    assert usage["input_tokens"] == sum(u["input_tokens"] for u in used) == 2_000
    assert usage["output_tokens"] == sum(u["output_tokens"] for u in used) == 321
    assert usage["cost_usd"] == pytest.approx(sum(u["cost_usd"] for u in used))
    assert usage["cost_inr"] == pytest.approx(sum(u["cost_inr"] for u in used))
    # 2000 x $0.40/M + 321 x $1.60/M, at ₹96 to the dollar (ADR 0027's default prices).
    assert usage["cost_usd"] == pytest.approx(0.0013136)
    assert usage["cost_inr"] == pytest.approx(0.0013136 * 96)
    assert usage["unpriced_models"] == []


@asynccontextmanager
async def served(app: FastAPI) -> AsyncIterator[str]:
    """`app` served over real HTTP on a free local port, so a response can stream."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, lifespan="off", log_level="warning")
    )
    task = asyncio.create_task(server.serve())
    for _ in range(1_000):
        if server.started:
            break
        await asyncio.sleep(0.01)
    else:
        raise AssertionError("the API server did not start")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task


async def test_events_stream_live_while_the_session_plans_and_decides(
    postgres_url: str, small_models: tuple[DemandModel, Relations]
) -> None:
    llm = GatedProvider(FakeProvider([READING, explainer_down()]))
    async with (
        api_app(postgres_url, llm, small_models) as app,
        served(app) as base_url,
        AsyncClient(base_url=base_url, timeout=30) as client,
    ):
        session_id = (await client.post("/api/sessions", json={"brief": BRIEF})).json()[
            "session_id"
        ]
        seen: list[dict[str, Any]] = []
        async with client.stream("GET", f"/api/sessions/{session_id}/events") as stream:
            lines = stream.aiter_lines()
            data = [line async for line in _data_lines(lines, count=1)]
            # The Context node has started, but its LLM call is held: planning goes on.
            seen += [json.loads(line) for line in data]
            assert (await client.get(f"/api/sessions/{session_id}")).json()["status"] == "planning"
            llm.gate.set()
            await settled(client, session_id)
            approved = await client.post(
                f"/api/sessions/{session_id}/approve", json={"revision_number": 1}
            )
            assert approved.status_code == 200
            seen += [json.loads(line) async for line in _data_lines(lines, count=None)]

    assert seen[0]["payload"]["kind"] == "node_started"
    assert seen[0]["node"] == "context"
    assert [event["id"] for event in seen if "id" in event] == list(
        range(1, len([e for e in seen if "id" in e]) + 1)
    )
    assert seen[-1] == {"session_id": session_id, "status": "approved"}


async def _data_lines(lines: AsyncIterator[str], count: int | None) -> AsyncIterator[str]:
    """The next `count` `data:` lines of an SSE stream, or all of them until it ends."""
    taken = 0
    async for line in lines:
        if line.startswith("data:"):
            yield line.removeprefix("data:").strip()
            taken += 1
            if count is not None and taken == count:
                return
