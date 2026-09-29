import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest
from pydantic import BaseModel

from promopilot.llm import (
    CassetteMissError,
    FakeProvider,
    Message,
    RecordingProvider,
    ReplayProvider,
    ToolCall,
    ToolSpec,
    ToolTurn,
    Usage,
    record_usage,
    request_hash,
    tool_request_hash,
    track_usage,
)


class Weather(BaseModel):
    city: str
    celsius: int


ASK = [Message(role="system", content="Extract."), Message(role="user", content="Pune, 31")]


async def test_replay_returns_the_recorded_response_for_an_identical_request(
    tmp_path: Path,
) -> None:
    recorder = RecordingProvider(FakeProvider([Weather(city="Pune", celsius=31)]), tmp_path)
    await recorder.complete_structured(Weather, ASK)

    replayed = await ReplayProvider(tmp_path).complete_structured(Weather, list(ASK))

    assert replayed == Weather(city="Pune", celsius=31)


async def test_replay_miss_raises_naming_the_request_hash(tmp_path: Path) -> None:
    recorder = RecordingProvider(FakeProvider([Weather(city="Pune", celsius=31)]), tmp_path)
    await recorder.complete_structured(Weather, ASK)
    changed = [*ASK[:1], Message(role="user", content="Pune, 32")]

    with pytest.raises(CassetteMissError) as miss:
        await ReplayProvider(tmp_path).complete_structured(Weather, changed)

    assert request_hash(Weather, changed) in str(miss.value)
    assert miss.value.digest == request_hash(Weather, changed)
    assert request_hash(Weather, changed) != request_hash(Weather, ASK)


async def test_a_changed_schema_is_a_different_request(tmp_path: Path) -> None:
    class WeatherV2(BaseModel):
        city: str
        celsius: float

    recorder = RecordingProvider(FakeProvider([Weather(city="Pune", celsius=31)]), tmp_path)
    await recorder.complete_structured(Weather, ASK)

    with pytest.raises(CassetteMissError):
        await ReplayProvider(tmp_path).complete_structured(WeatherV2, ASK)


async def test_a_recorded_cassette_has_lf_line_endings_on_every_platform(
    tmp_path: Path,
) -> None:
    recorder = RecordingProvider(FakeProvider([Weather(city="Pune", celsius=31)]), tmp_path)
    await recorder.complete_structured(Weather, ASK)

    assert b"\r" not in read_bytes(tmp_path / f"{request_hash(Weather, ASK)}.json")


def read_bytes(path: Path) -> bytes:
    return path.read_bytes()


def test_request_hash_is_stable_across_processes() -> None:
    script = (
        "from tests.unit.llm.test_replay_provider import ASK, Weather;"
        "from promopilot.llm import request_hash;"
        "print(request_hash(Weather, ASK))"
    )
    hashes = {
        subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
        ).stdout.strip()
        for seed in ("1", "2")
    }

    assert hashes == {request_hash(Weather, ASK)}


FORECAST = ToolSpec(
    name="get_forecast",
    description="Forecast for a city.",
    input_schema={"type": "object", "properties": {"city": {"type": "string"}}},
)
CALL = ToolCall(id="call_1", name="get_forecast", arguments={"city": "Pune"})
TOOL_ROUND = [
    Message(role="user", content="Weather in Pune?"),
    Message(role="assistant", content="", tool_calls=(CALL,)),
    Message(role="tool", content='{"celsius": 31}', tool_call_id="call_1"),
]


async def test_replay_answers_a_recorded_tool_call(tmp_path: Path) -> None:
    turn = ToolTurn(text="It is 31 C in Pune.")
    await RecordingProvider(FakeProvider([turn]), tmp_path).complete_with_tools(
        [FORECAST], TOOL_ROUND
    )

    replayed = await ReplayProvider(tmp_path).complete_with_tools([FORECAST], list(TOOL_ROUND))

    assert replayed == turn


async def test_a_tool_request_misses_when_the_tools_change(tmp_path: Path) -> None:
    await RecordingProvider(FakeProvider([ToolTurn(text="31 C")]), tmp_path).complete_with_tools(
        [FORECAST], TOOL_ROUND
    )
    renamed = FORECAST.model_copy(update={"description": "Forecast for a town."})

    with pytest.raises(CassetteMissError, match=tool_request_hash([renamed], TOOL_ROUND)):
        await ReplayProvider(tmp_path).complete_with_tools([renamed], TOOL_ROUND)


def test_the_tool_call_ids_are_part_of_the_tool_request_hash() -> None:
    other_id = [
        TOOL_ROUND[0],
        Message(role="assistant", content="", tool_calls=(CALL.model_copy(update={"id": "c2"}),)),
        TOOL_ROUND[2].model_copy(update={"tool_call_id": "c2"}),
    ]

    assert tool_request_hash([FORECAST], other_id) != tool_request_hash([FORECAST], TOOL_ROUND)


def test_tool_results_are_left_out_of_the_tool_request_hash() -> None:
    # Tool outputs carry model ids and solver evidence that change on every machine and every
    # retrain; a replayed tool round must not depend on them (ADR 0049).
    other_result = [*TOOL_ROUND[:2], TOOL_ROUND[2].model_copy(update={"content": '{"c": 29}'})]

    assert tool_request_hash([FORECAST], other_result) == tool_request_hash([FORECAST], TOOL_ROUND)


def test_the_tool_call_arguments_stay_in_the_tool_request_hash() -> None:
    other_city = CALL.model_copy(update={"arguments": {"city": "Nagpur"}})
    other_arguments = [
        TOOL_ROUND[0],
        Message(role="assistant", content="", tool_calls=(other_city,)),
        TOOL_ROUND[2],
    ]

    assert tool_request_hash([FORECAST], other_arguments) != tool_request_hash(
        [FORECAST], TOOL_ROUND
    )


async def test_a_recorded_tool_round_replays_when_the_tool_result_differs(tmp_path: Path) -> None:
    turn = ToolTurn(text="It is warm in Pune.")
    await RecordingProvider(FakeProvider([turn]), tmp_path).complete_with_tools(
        [FORECAST], TOOL_ROUND
    )
    later = [*TOOL_ROUND[:2], TOOL_ROUND[2].model_copy(update={"content": '{"celsius": 33}'})]

    assert await ReplayProvider(tmp_path).complete_with_tools([FORECAST], later) == turn


def test_provider_state_is_left_out_of_the_hash() -> None:
    thinking = {"type": "thinking", "thinking": "", "signature": "sig-abc"}
    with_state = [
        TOOL_ROUND[0],
        TOOL_ROUND[1].model_copy(update={"provider_state": (thinking,)}),
        TOOL_ROUND[2],
    ]

    assert tool_request_hash([FORECAST], with_state) == tool_request_hash([FORECAST], TOOL_ROUND)


def test_a_plain_message_hashes_as_before_the_tool_fields_existed() -> None:
    # The committed cassettes were hashed over {role, content}: empty tool fields add nothing.
    before = {
        "schema": Weather.model_json_schema(),
        "messages": [{"role": m.role, "content": m.content} for m in ASK],
        "temperature": 0.0,
    }
    canonical = json.dumps(before, sort_keys=True, separators=(",", ":")).encode("utf-8")

    assert request_hash(Weather, ASK) == hashlib.sha256(canonical).hexdigest()


class BilledFake(FakeProvider):
    """A fake that reports usage for each call, as live providers do."""

    async def complete_with_tools(
        self, tools: Sequence[ToolSpec], messages: Sequence[Message]
    ) -> ToolTurn:
        record_usage(Usage(model="gpt-4.1-mini", input_tokens=120, output_tokens=30))
        return await super().complete_with_tools(tools, messages)


async def test_a_cassette_records_usage_that_replay_reports_again(tmp_path: Path) -> None:
    with track_usage() as recording:
        await RecordingProvider(BilledFake([ToolTurn(text="31 C")]), tmp_path).complete_with_tools(
            [FORECAST], TOOL_ROUND
        )
    with track_usage() as replaying:
        await ReplayProvider(tmp_path).complete_with_tools([FORECAST], TOOL_ROUND)

    billed = Usage(model="gpt-4.1-mini", input_tokens=120, output_tokens=30)
    assert recording.usages == (billed,)
    assert replaying.usages == (billed,)
    cassette = json.loads(only_cassette(tmp_path).read_text(encoding="utf-8"))
    assert cassette["usage"] == [billed.model_dump()]
    assert "usage" not in cassette["request"]


async def test_a_cassette_without_usage_replays_with_none(tmp_path: Path) -> None:
    await RecordingProvider(
        FakeProvider([Weather(city="Pune", celsius=31)]), tmp_path
    ).complete_structured(Weather, ASK)
    path = only_cassette(tmp_path)
    cassette = json.loads(path.read_text(encoding="utf-8"))
    del cassette["usage"]
    path.write_text(json.dumps(cassette), encoding="utf-8")

    with track_usage() as meter:
        await ReplayProvider(tmp_path).complete_structured(Weather, ASK)

    assert meter.usages == ()


def only_cassette(cassette_dir: Path) -> Path:
    [cassette] = cassette_dir.glob("*.json")
    return cassette


async def test_a_request_already_recorded_is_answered_from_its_cassette_not_asked_again(
    tmp_path: Path,
) -> None:
    # A live model can answer the same request differently each time, but a cassette keeps one
    # answer: had the recorder asked again, the conversation that went on from the first answer
    # would not replay from the cassette that kept the second (ADR 0054).
    live = FakeProvider([Weather(city="Pune", celsius=31), Weather(city="Pune", celsius=32)])
    recorder = RecordingProvider(live, tmp_path)

    first = await recorder.complete_structured(Weather, ASK)
    again = await recorder.complete_structured(Weather, list(ASK))

    assert again == first == Weather(city="Pune", celsius=31)
    assert len(live.calls) == 1
    assert await ReplayProvider(tmp_path).complete_structured(Weather, ASK) == first


async def test_a_tool_request_already_recorded_is_answered_from_its_cassette(
    tmp_path: Path,
) -> None:
    live = FakeProvider([ToolTurn(text="31 C"), ToolTurn(text="32 C")])
    recorder = RecordingProvider(live, tmp_path)

    first = await recorder.complete_with_tools([], ASK)
    again = await recorder.complete_with_tools([], list(ASK))

    assert again == first == ToolTurn(text="31 C")
    assert len(live.calls) == 1
