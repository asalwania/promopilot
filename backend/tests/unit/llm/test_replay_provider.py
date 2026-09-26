import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel

from promopilot.llm import (
    CassetteMissError,
    FakeProvider,
    Message,
    RecordingProvider,
    ReplayProvider,
    request_hash,
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
