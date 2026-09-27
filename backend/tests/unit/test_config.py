"""Runtime configuration read from the environment (.env.example)."""

import pytest

from promopilot.config import Settings


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
