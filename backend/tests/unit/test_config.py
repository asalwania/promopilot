"""Runtime configuration read from the environment (.env.example)."""

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import create_async_engine

from promopilot.api.planning import build_planning
from promopilot.config import Settings
from promopilot.guardrails import RiskThresholds


def test_the_optimiser_is_deterministic_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "OPTIMIZER_TIME_LIMIT_SECONDS",
        "OPTIMIZER_WORKERS",
        "OPTIMIZER_SEED",
        "OPTIMIZER_BINDING_TIME_LIMIT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings()

    assert settings.optimizer_binding_time_limit_seconds == 8.0
    assert settings.optimizer_time_limit_seconds == 10.0
    assert settings.optimizer_workers == 1
    assert settings.optimizer_seed == 0


def test_the_optimisers_time_limit_workers_and_seed_come_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPTIMIZER_TIME_LIMIT_SECONDS", "2.5")
    monkeypatch.setenv("OPTIMIZER_WORKERS", "4")
    monkeypatch.setenv("OPTIMIZER_SEED", "7")
    monkeypatch.setenv("OPTIMIZER_BINDING_TIME_LIMIT_SECONDS", "0")

    settings = Settings()

    assert settings.optimizer_binding_time_limit_seconds == 0.0
    assert settings.optimizer_time_limit_seconds == 2.5
    assert settings.optimizer_workers == 4
    assert settings.optimizer_seed == 7
    with monkeypatch.context() as patched:
        patched.setenv("OPTIMIZER_WORKERS", "0")
        with pytest.raises(ValueError, match="optimizer_workers"):
            Settings()


def test_the_simulation_runs_1000_times_with_seed_0_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SIMULATION_RUNS", raising=False)
    monkeypatch.delenv("SIMULATION_SEED", raising=False)

    settings = Settings()

    assert settings.simulation_runs == 1_000
    assert settings.simulation_seed == 0


def test_the_simulation_runs_and_seed_come_from_the_environment_within_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMULATION_RUNS", "250")
    monkeypatch.setenv("SIMULATION_SEED", "9")

    settings = Settings()

    assert (settings.simulation_runs, settings.simulation_seed) == (250, 9)
    for runs in ("99", "5001"):
        with monkeypatch.context() as patched:
            patched.setenv("SIMULATION_RUNS", runs)
            with pytest.raises(ValueError, match="simulation_runs"):
                Settings()


def test_the_trace_polls_twice_a_second_and_logs_json_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TRACE_POLL_INTERVAL_S", raising=False)
    monkeypatch.delenv("LOG_FORMAT", raising=False)

    settings = Settings()

    assert settings.trace_poll_interval_s == 0.5
    assert settings.log_format == "json"


def test_the_trace_poll_interval_and_log_format_come_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRACE_POLL_INTERVAL_S", "0.2")
    monkeypatch.setenv("LOG_FORMAT", "console")

    settings = Settings()

    assert settings.trace_poll_interval_s == 0.2
    assert settings.log_format == "console"
    monkeypatch.setenv("LOG_FORMAT", "xml")
    with pytest.raises(ValueError, match="log_format"):
        Settings()


def test_the_critics_risk_thresholds_come_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CRITIC_LINE_SPEND_SHARE", "0.3")
    monkeypatch.setenv("CRITIC_GROUP_SPEND_SHARE", "0.9")
    monkeypatch.setenv("CRITIC_CANNIBALISATION_SHARE", "0.6")
    monkeypatch.setenv("CRITIC_STOCKOUT_PROBABILITY", "0.1")
    engine = create_async_engine("postgresql+asyncpg://unused@127.0.0.1:1/unused")

    planning = build_planning(Settings(), engine)

    assert planning.risk_thresholds == RiskThresholds(
        line_spend_share=0.3,
        group_spend_share=0.9,
        cannibalisation_share=0.6,
        stockout_probability=0.1,
    )
    with monkeypatch.context() as patched:
        patched.setenv("CRITIC_STOCKOUT_PROBABILITY", "1.5")
        with pytest.raises(ValidationError):
            Settings()


def test_the_critics_risk_thresholds_default_to_adr_0051(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "CRITIC_LINE_SPEND_SHARE",
        "CRITIC_GROUP_SPEND_SHARE",
        "CRITIC_CANNIBALISATION_SHARE",
        "CRITIC_STOCKOUT_PROBABILITY",
    ):
        monkeypatch.delenv(name, raising=False)
    engine = create_async_engine("postgresql+asyncpg://unused@127.0.0.1:1/unused")

    assert build_planning(Settings(), engine).risk_thresholds == RiskThresholds()
