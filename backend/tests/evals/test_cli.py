"""`python -m promopilot.evals` (`make eval`) runs scenarios and writes the report (ADR 0056)."""

import json
from pathlib import Path

import pytest

import promopilot.evals.__main__ as cli
from promopilot.evals.__main__ import main
from tests.conftest import SMALL_AS_OF, SMALL_OVERRIDES
from tests.unit.agents.fakes import DownProvider

SCENARIO = f"""\
name: plain
group: standard_festive
brief: "Plan a Diwali promotion for Snacks in North with a marketing budget of ₹20k."
as_of_week: {SMALL_AS_OF}
seed: 1
expect:
  - excludes_region: South
"""


@pytest.fixture
def paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    scenarios, reports, cassettes = tmp_path / "scenarios", tmp_path / "reports", tmp_path / "c"
    scenarios.mkdir()
    cassettes.mkdir()
    (scenarios / "plain.yaml").write_text(SCENARIO, encoding="utf-8")
    other = SCENARIO.replace("name: plain", "name: other")
    (scenarios / "other.yaml").write_text(other, encoding="utf-8")
    config = tmp_path / "small.yaml"
    config.write_text(json.dumps(SMALL_OVERRIDES), encoding="utf-8")
    # Replay with no cassettes: every LLM step misses and falls back, with no key and no network.
    monkeypatch.setenv("LLM_PROVIDER", "replay")
    monkeypatch.setenv("LLM_CASSETTE_DIR", str(cassettes))
    monkeypatch.setenv("SIMULATION_RUNS", "200")
    return scenarios, reports, config


def test_it_runs_the_chosen_scenarios_on_the_replay_provider_and_writes_the_report(
    paths: tuple[Path, Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    scenarios, reports, config = paths

    code = main(
        [
            "--scenarios",
            str(scenarios),
            "--only",
            "plain",
            "--seed",
            "11",
            "--config",
            str(config),
            "--out",
            str(reports),
        ]
    )

    assert code == 0
    report = json.loads((reports / "latest.json").read_text(encoding="utf-8"))
    assert report["provider"] == "replay"
    assert report["world_seed"] == 11
    assert [scenario["name"] for scenario in report["scenarios"]] == ["plain"]
    [played] = report["scenarios"][0]["runs"]
    assert "context: cassette_missing" in played["fallbacks"]
    assert (reports / "latest.md").is_file()
    assert len(list(reports.glob("*.json"))) == 2, "the timestamped report and latest"
    printed = capsys.readouterr().out
    assert "Constraint satisfaction" in printed
    assert "latest.md" in printed


def test_an_unknown_scenario_name_is_refused(
    paths: tuple[Path, Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    scenarios, reports, _ = paths

    code = main(["--scenarios", str(scenarios), "--only", "nope", "--out", str(reports)])

    assert code == 2
    assert "nope" in capsys.readouterr().err
    assert not reports.exists()


def test_an_invalid_scenario_file_is_refused(
    paths: tuple[Path, Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    scenarios, reports, _ = paths
    (scenarios / "broken.yaml").write_text("name: broken\n", encoding="utf-8")

    code = main(["--scenarios", str(scenarios), "--out", str(reports)])

    assert code == 1
    assert "broken" in capsys.readouterr().err


def test_recording_needs_a_live_provider(
    paths: tuple[Path, Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    scenarios, reports, _ = paths

    code = main(["--scenarios", str(scenarios), "--record", "--out", str(reports)])

    assert code == 2
    assert "LLM_PROVIDER=replay" in capsys.readouterr().err
    assert not reports.exists()


def test_recording_plays_the_scenarios_live_into_the_eval_cassettes_and_says_what_it_cost(
    paths: tuple[Path, Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    scenarios, reports, config = paths
    eval_cassettes = tmp_path / "eval-cassettes"
    live = DownProvider()
    # A live provider that is down: no key and no network, and every step falls back.
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setattr(cli, "build_provider", lambda settings: live)

    code = main(
        [
            "--scenarios",
            str(scenarios),
            "--only",
            "plain",
            "--config",
            str(config),
            "--out",
            str(reports),
            "--cassettes",
            str(eval_cassettes),
            "--record",
        ]
    )

    assert code == 0
    assert live.calls > 0, "the live provider was asked"
    report = json.loads((reports / "latest.json").read_text(encoding="utf-8"))
    assert report["provider"] == "openai (recording)"
    printed = capsys.readouterr().out
    assert f"recorded into {eval_cassettes}" in printed
    assert "0 live calls" in printed


def test_smoke_plays_only_the_tagged_scenarios_and_check_fails_on_every_cassette_miss(
    paths: tuple[Path, Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    scenarios, reports, config = paths
    (scenarios / "plain.yaml").write_text(SCENARIO + "smoke: true\n", encoding="utf-8")

    code = main(
        [
            "--scenarios",
            str(scenarios),
            "--config",
            str(config),
            "--out",
            str(reports),
            "--smoke",
            "--check",
        ]
    )

    assert code == 3
    report = json.loads((reports / "latest.json").read_text(encoding="utf-8"))
    assert [scenario["name"] for scenario in report["scenarios"]] == ["plain"]
    [played] = report["scenarios"][0]["runs"]
    assert played["cassette_misses"], "no cassette is recorded"
    err = capsys.readouterr().err
    assert "check failed" in err
    assert f"plain run 1: {len(played['cassette_misses'])} requests no cassette holds" in err


def test_check_passes_a_report_with_no_problem(
    paths: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    scenarios, reports, config = paths
    monkeypatch.setattr(cli, "report_problems", lambda report: [])

    code = main(
        [
            "--scenarios",
            str(scenarios),
            "--only",
            "plain",
            "--config",
            str(config),
            "--out",
            str(reports),
            "--check",
        ]
    )

    assert code == 0
    assert "check passed" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("args", "problem"),
    [
        (["--smoke", "--only", "plain"], "--smoke"),
        (["--smoke"], "no smoke scenario"),
    ],
)
def test_smoke_is_refused_with_only_or_with_no_tagged_scenario(
    paths: tuple[Path, Path, Path],
    capsys: pytest.CaptureFixture[str],
    args: list[str],
    problem: str,
) -> None:
    scenarios, reports, _ = paths

    code = main(["--scenarios", str(scenarios), "--out", str(reports), *args])

    assert code == 2
    assert problem in capsys.readouterr().err
    assert not reports.exists()


def test_check_needs_the_replay_provider(
    paths: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    scenarios, reports, _ = paths
    monkeypatch.setenv("LLM_PROVIDER", "openai")

    code = main(["--scenarios", str(scenarios), "--out", str(reports), "--check"])

    assert code == 2
    assert "--check replays" in capsys.readouterr().err
    assert not reports.exists()
