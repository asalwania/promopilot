"""Trace emission (SF-01, #45, ADR 0047): `emit` inside a traced node, token usage per billed
LLM call, and tool calls through the traced tool registry."""

import json
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, JsonValue

from promopilot.agents import (
    LLMPricing,
    MemoryTrace,
    TracedProvider,
    TracedToolRegistry,
    emit,
    summarize,
    traced_node,
)
from promopilot.agents.tools import Tool, ToolCallError, ToolRegistry
from promopilot.config import ModelPrice
from promopilot.domain import (
    DecisionMade,
    NodeFinished,
    NodeOutcome,
    NodeStarted,
    TokensUsed,
    ToolCalled,
)
from promopilot.llm import FakeProvider, LLMError, Message, Usage
from tests.unit.agents.billed import BilledProvider

PRICING = LLMPricing(
    prices={"gpt-4.1-mini": ModelPrice(input_usd_per_mtok=0.40, output_usd_per_mtok=1.60)},
    usd_inr_rate=96.0,
)


class Answer(BaseModel):
    text: str


class State(BaseModel):
    session_id: UUID


def node_state() -> State:
    return State(session_id=uuid4())


async def test_emit_outside_a_traced_node_is_dropped() -> None:
    await emit(DecisionMade(decision="nothing", summary="No node is running."))


async def test_a_traced_node_records_its_start_what_it_emits_and_its_end() -> None:
    trace = MemoryTrace()
    state = node_state()

    async def critic(state: State) -> dict[str, object]:
        await emit(DecisionMade(decision="plan_valid", summary="The plan passes validation."))
        return {"ok": True}

    result = await traced_node(trace, "critic", critic)(state)

    assert result == {"ok": True}
    events = trace.of(state.session_id)
    assert [event.id for event in events] == [1, 2, 3]
    assert {event.node for event in events} == {"critic"}
    started, decided, finished = (event.payload for event in events)
    assert started == NodeStarted()
    assert decided == DecisionMade(decision="plan_valid", summary="The plan passes validation.")
    assert isinstance(finished, NodeFinished)
    assert finished.outcome is NodeOutcome.COMPLETED
    assert finished.error is None


async def test_a_failing_node_ends_failed_with_its_error_and_still_raises() -> None:
    trace = MemoryTrace()
    state = node_state()

    async def planner(state: State) -> dict[str, object]:
        raise RuntimeError("no trained model")

    with pytest.raises(RuntimeError, match="no trained model"):
        await traced_node(trace, "planner", planner)(state)

    finished = trace.of(state.session_id)[-1].payload
    assert isinstance(finished, NodeFinished)
    assert finished.outcome is NodeOutcome.FAILED
    assert finished.error == "no trained model"


async def test_each_session_numbers_its_own_events_from_one() -> None:
    trace = MemoryTrace()
    first, second = node_state(), node_state()

    async def node(state: State) -> dict[str, object]:
        return {}

    await traced_node(trace, "context", node)(first)
    await traced_node(trace, "context", node)(second)

    assert [e.id for e in trace.of(first.session_id)] == [1, 2]
    assert [e.id for e in trace.of(second.session_id)] == [1, 2]


async def test_every_billed_llm_call_is_a_priced_token_usage_event() -> None:
    trace = MemoryTrace()
    state = node_state()
    llm = TracedProvider(
        BilledProvider(
            FakeProvider([Answer(text="a"), Answer(text="b")]),
            [
                Usage(model="gpt-4.1-mini", input_tokens=1_000, output_tokens=500),
                Usage(model="gpt-4.1-mini", input_tokens=2_000, output_tokens=0),
            ],
        ),
        PRICING,
    )

    async def context(state: State) -> dict[str, object]:
        await llm.complete_structured(Answer, [Message(role="user", content="hi")])
        await llm.complete_structured(Answer, [Message(role="user", content="again")])
        return {}

    await traced_node(trace, "context", context)(state)

    usages = [e.payload for e in trace.of(state.session_id) if isinstance(e.payload, TokensUsed)]
    # 1000 x $0.40/M + 500 x $1.60/M = $0.0012; 2000 x $0.40/M = $0.0008
    assert [(u.input_tokens, u.output_tokens) for u in usages] == [(1_000, 500), (2_000, 0)]
    assert [u.cost_usd for u in usages] == pytest.approx([0.0012, 0.0008])
    assert [u.cost_inr for u in usages] == pytest.approx([0.1152, 0.0768])


async def test_an_unpriced_model_counts_its_tokens_with_no_cost() -> None:
    trace = MemoryTrace()
    state = node_state()
    llm = TracedProvider(
        BilledProvider(
            FakeProvider([Answer(text="a")]),
            [Usage(model="mystery-model", input_tokens=10, output_tokens=5)],
        ),
        PRICING,
    )

    async def context(state: State) -> dict[str, object]:
        await llm.complete_structured(Answer, [Message(role="user", content="hi")])
        return {}

    await traced_node(trace, "context", context)(state)

    [usage] = [e.payload for e in trace.of(state.session_id) if isinstance(e.payload, TokensUsed)]
    assert (usage.model, usage.input_tokens, usage.cost_usd, usage.cost_inr) == (
        "mystery-model",
        10,
        None,
        None,
    )


async def test_a_failed_call_that_was_billed_still_reports_its_usage() -> None:
    trace = MemoryTrace()
    state = node_state()
    llm = TracedProvider(
        BilledProvider(
            FakeProvider([LLMError("refused")]),
            [Usage(model="gpt-4.1-mini", input_tokens=100, output_tokens=3)],
        ),
        PRICING,
    )

    async def context(state: State) -> dict[str, object]:
        await llm.complete_structured(Answer, [Message(role="user", content="hi")])
        return {}

    with pytest.raises(LLMError):
        await traced_node(trace, "context", context)(state)

    kinds = [e.payload.kind for e in trace.of(state.session_id)]
    assert kinds == ["node_started", "token_usage", "node_finished"]


class Lookup(BaseModel):
    sku_id: str


class Found(BaseModel):
    sku_id: str
    price: float
    stores: list[str]


def registry() -> ToolRegistry:
    async def lookup(arguments: Lookup) -> Found:
        if arguments.sku_id == "missing":
            raise ToolCallError("data_unavailable", "no such SKU")
        return Found(sku_id=arguments.sku_id, price=99.0, stores=["S1", "S2", "S3"])

    return ToolRegistry(
        [Tool("lookup", "Look a SKU up.", Lookup, Found, lookup)],
    )


async def test_a_traced_tool_call_records_its_arguments_and_result_summary() -> None:
    trace = MemoryTrace()
    state = node_state()
    tools = TracedToolRegistry(registry())

    async def planner(state: State) -> dict[str, object]:
        result = await tools.call("lookup", {"sku_id": "SKU0001"})
        assert result.ok
        return {}

    await traced_node(trace, "planner", planner)(state)

    [called] = [e.payload for e in trace.of(state.session_id) if isinstance(e.payload, ToolCalled)]
    assert called == ToolCalled(
        tool="lookup",
        arguments={"sku_id": "SKU0001"},
        ok=True,
        result_summary={"sku_id": "SKU0001", "price": 99.0, "stores": "<3 items>"},
    )
    assert tools.specs() == registry().specs()


async def test_a_tool_error_is_traced_with_its_code() -> None:
    trace = MemoryTrace()
    state = node_state()
    tools = TracedToolRegistry(registry())

    async def planner(state: State) -> dict[str, object]:
        result = await tools.call("lookup", {"sku_id": "missing"})
        assert not result.ok
        return {}

    await traced_node(trace, "planner", planner)(state)

    [called] = [e.payload for e in trace.of(state.session_id) if isinstance(e.payload, ToolCalled)]
    assert (called.ok, called.error_code) == (False, "data_unavailable")
    assert called.result_summary == {"message": "no such SKU", "details": "<0 items>"}


def test_a_summary_keeps_scalars_counts_lists_and_stops_two_levels_deep() -> None:
    value: JsonValue = {
        "status": "OPTIMAL",
        "objective": 6250.5,
        "lines": [{"sku_id": "A"}, {"sku_id": "B"}],
        "plan": {"totals": {"cost": 1.0}, "region": "North"},
        "none": None,
    }

    assert summarize(value) == {
        "status": "OPTIMAL",
        "objective": 6250.5,
        "lines": "<2 items>",
        "plan": {"totals": "<object with 1 fields>", "region": "North"},
        "none": None,
    }


def test_a_summary_longer_than_the_cap_is_cut_short() -> None:
    value: JsonValue = {f"field_{i}": "x" * 50 for i in range(100)}

    summary = summarize(value)

    assert isinstance(summary, str)
    assert len(summary) == 2048
    assert summary.endswith("…")
    assert summary.startswith(json.dumps(value, ensure_ascii=False)[:100])
