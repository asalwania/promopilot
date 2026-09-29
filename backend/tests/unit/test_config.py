"""Runtime configuration read from the environment (.env.example)."""

from pathlib import Path

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
        "OPTIMIZER_RELAXATION_TIME_LIMIT_SECONDS",
        "OPTIMIZER_DETERMINISTIC_LIMIT",
        "OPTIMIZER_BINDING_DETERMINISTIC_LIMIT",
        "OPTIMIZER_RELAXATION_DETERMINISTIC_LIMIT",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings()

    # Work budgets decide the plan; wall-clock limits are only safety nets (ADR 0055).
    assert settings.optimizer_deterministic_limit == 10.0
    assert settings.optimizer_binding_deterministic_limit == 6.0
    assert settings.optimizer_relaxation_deterministic_limit == 10.0
    assert settings.optimizer_binding_time_limit_seconds == 30.0
    assert settings.optimizer_time_limit_seconds == 60.0
    assert settings.optimizer_relaxation_time_limit_seconds == 60.0
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


def test_the_optimisers_work_budgets_reach_the_solver_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPTIMIZER_DETERMINISTIC_LIMIT", "4")
    monkeypatch.setenv("OPTIMIZER_BINDING_DETERMINISTIC_LIMIT", "0")
    monkeypatch.setenv("OPTIMIZER_RELAXATION_DETERMINISTIC_LIMIT", "3")
    engine = create_async_engine("postgresql+asyncpg://unused@127.0.0.1:1/unused")

    solver = build_planning(Settings(), engine).solver

    assert (
        solver.deterministic_limit,
        solver.binding_deterministic_limit,
        solver.relaxation_deterministic_limit,
    ) == (4.0, 0.0, 3.0)
    with monkeypatch.context() as patched:
        patched.setenv("OPTIMIZER_DETERMINISTIC_LIMIT", "0")
        with pytest.raises(ValidationError):
            Settings()


def test_the_planning_settings_a_recording_depends_on_come_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # What the LLM is shown depends on these, so a recording notes them and the check compares
    # them with the replaying stack's (ADR 0054).
    for name in RECORDED:
        monkeypatch.delenv(name.upper(), raising=False)
    monkeypatch.setenv("SIMULATION_RUNS", "200")
    monkeypatch.setenv("CRITIC_STOCKOUT_PROBABILITY", "0.1")
    engine = create_async_engine("postgresql+asyncpg://unused@127.0.0.1:1/unused")

    planning = build_planning(Settings(), engine)

    assert set(planning.recorded_settings) == set(RECORDED)
    assert planning.recorded_settings == {
        "optimizer_deterministic_limit": 10.0,
        "optimizer_binding_deterministic_limit": 6.0,
        "optimizer_relaxation_deterministic_limit": 10.0,
        "optimizer_time_limit_seconds": 60.0,
        "optimizer_workers": 1,
        "optimizer_seed": 0,
        "optimizer_binding_time_limit_seconds": 30.0,
        "optimizer_relaxation_time_limit_seconds": 60.0,
        "simulation_runs": 200,
        "simulation_seed": 0,
        "critic_line_spend_share": 0.25,
        "critic_group_spend_share": 0.8,
        "critic_cannibalisation_share": 0.5,
        "critic_stockout_probability": 0.1,
    }
    recorded = planning.recorded()
    assert recorded.settings == planning.recorded_settings
    assert recorded.risk_thresholds == planning.risk_thresholds
    assert recorded.policy == planning.policy
    assert recorded.default is planning.planner


RECORDED = (
    # The work budgets decide the plan (ADR 0055); the wall-clock nets only when one is hit.
    "optimizer_deterministic_limit",
    "optimizer_binding_deterministic_limit",
    "optimizer_relaxation_deterministic_limit",
    "optimizer_time_limit_seconds",
    "optimizer_workers",
    "optimizer_seed",
    "optimizer_binding_time_limit_seconds",
    "optimizer_relaxation_time_limit_seconds",
    "simulation_runs",
    "simulation_seed",
    "critic_line_spend_share",
    "critic_group_spend_share",
    "critic_cannibalisation_share",
    "critic_stockout_probability",
)


def test_the_api_serves_the_eval_report_make_eval_writes_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EVAL_REPORT_DIR", raising=False)
    assert Settings().eval_report_dir == Path("evals/reports")

    monkeypatch.setenv("EVAL_REPORT_DIR", "/srv/reports")
    assert Settings().eval_report_dir == Path("/srv/reports")
