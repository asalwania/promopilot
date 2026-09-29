"""`make demo`'s init step (ADR 0073): load the seed-42 world and train the models into the
volume, skipping whatever is already done, and say what it does as it goes."""

import pytest

from promopilot.demo import prepare, run


class FakeDemo:
    def __init__(self, *, loaded: bool, trained: bool) -> None:
        self.loaded = loaded
        self.trained = trained
        self.done: list[str] = []

    async def data_loaded(self) -> bool:
        return self.loaded

    async def models_ready(self) -> bool:
        return self.trained

    async def load_data(self) -> None:
        self.done.append("load")
        self.loaded = True

    async def train(self) -> None:
        self.done.append("train")
        self.trained = True


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        self.now += 30.0
        return self.now


async def test_a_fresh_stack_loads_the_data_then_trains_and_says_so() -> None:
    demo = FakeDemo(loaded=False, trained=False)
    lines: list[str] = []

    await prepare(demo, say=lines.append, clock=Clock())

    assert demo.done == ["load", "train"]
    assert lines[0].startswith("[1/2] Generating the seed-42 world and loading it")
    assert lines[1] == "      done in 30 s"
    assert lines[2].startswith("[2/2] Training the demand and relations models")
    assert lines[4] == "Demo data and models are ready."


async def test_a_restart_skips_what_is_done() -> None:
    demo = FakeDemo(loaded=True, trained=True)
    lines: list[str] = []

    await prepare(demo, say=lines.append, clock=Clock())

    assert demo.done == []
    assert lines == [
        "[1/2] The seed-42 world is already loaded: skipped.",
        "[2/2] The models are already trained: skipped.",
        "Demo data and models are ready.",
    ]


async def test_models_missing_from_the_volume_are_trained_again_on_the_loaded_data() -> None:
    demo = FakeDemo(loaded=True, trained=False)

    await prepare(demo, say=lambda _: None, clock=Clock())

    assert demo.done == ["train"]


class BrokenDemo(FakeDemo):
    async def train(self) -> None:
        raise LookupError("no sales history is loaded; run `make data`")


async def test_the_cli_exits_non_zero_naming_what_failed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "promopilot.demo.PostgresDemo", lambda **_: BrokenDemo(loaded=True, trained=False)
    )

    assert await run([]) == 1
    assert "no sales history is loaded" in capsys.readouterr().err
