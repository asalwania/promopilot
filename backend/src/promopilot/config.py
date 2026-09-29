"""Runtime configuration, read from environment variables (see .env.example)."""

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelPrice(BaseModel):
    """What one LLM model costs, in US dollars per million tokens (ADR 0027)."""

    model_config = ConfigDict(frozen=True)

    input_usd_per_mtok: float = Field(ge=0)
    output_usd_per_mtok: float = Field(ge=0)


# Standard-tier list prices checked on 2026-09-26 (sources in ADR 0027).
DEFAULT_LLM_PRICES = {
    "gpt-4.1-mini": ModelPrice(input_usd_per_mtok=0.40, output_usd_per_mtok=1.60),
    "claude-sonnet-5": ModelPrice(input_usd_per_mtok=2.00, output_usd_per_mtok=10.00),
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    database_url: str = "postgresql+asyncpg://promopilot:promopilot@localhost:5432/promopilot"

    # Trained model artifacts (ADR 0023); the registry rows hold paths relative to it.
    # Relative paths are from backend/.
    model_dir: Path = Path("../models")

    # LLM layer (ADR 0001, ADR 0019, ADR 0027). `replay` needs no key; relative paths are from
    # backend/. The live provider not chosen by LLM_PROVIDER is the fallback, when configured.
    # `auto` (the demo, ADR 0073) is resolved here, before anything reads it: openai when its
    # key is set, else anthropic when its key is set, else replay.
    llm_provider: Literal["openai", "anthropic", "replay", "fake"] = "replay"
    llm_cassette_dir: Path = Path("cassettes")
    openai_api_key: SecretStr | None = None
    openai_model: str | None = None
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str | None = None
    # Per-model prices (LLM_PRICES, JSON) and the rupee rate for per-session cost (ADR 0027).
    llm_prices: dict[str, ModelPrice] = Field(default_factory=lambda: dict(DEFAULT_LLM_PRICES))
    usd_inr_rate: float = Field(default=96.0, gt=0)

    # Where `GET /api/evals/latest` reads `latest.json` from (ADR 0069): by default the folder
    # `make eval` writes. Relative paths are from backend/.
    eval_report_dir: Path = Path("evals/reports")

    # Timeouts (ADR 0071), in wall-clock seconds. An LLM attempt that has not answered is a
    # transient error: retried, then the fallback provider, then the agents' graceful
    # degradation. A tool call that has not answered is a `timeout` tool error; its worker
    # thread is abandoned, and the optimiser's own nets still stop it. A background graph run
    # (start, or the resume after clarify or amend) that has not paused fails the session.
    llm_timeout_seconds: float = Field(default=60.0, gt=0)
    tool_timeout_seconds: float = Field(default=120.0, gt=0)
    session_timeout_seconds: float = Field(default=900.0, gt=0)
    # The largest request body the API reads (ADR 0071); a larger one is 413.
    max_request_body_bytes: int = Field(default=256 * 1024, ge=1024)

    # The live trace (ADR 0047): how often an open SSE stream looks for new trace events, in
    # seconds, and whether logs are JSON lines (`json`) or readable text (`console`).
    trace_poll_interval_s: float = Field(default=0.5, gt=0, le=10)
    log_format: Literal["json", "console"] = "json"

    # The CP-SAT optimiser (ADR 0036). One worker and a fixed seed give the same plan for the
    # same input; more workers interleave their search deterministically. Each phase stops on
    # a budget of CP-SAT deterministic seconds (work done, the same on any machine), so a plan
    # never depends on how fast or busy the machine is; the *_TIME_LIMIT_SECONDS are
    # wall-clock safety nets a healthy machine never reaches (ADR 0055).
    optimizer_deterministic_limit: float = Field(default=10.0, gt=0)
    optimizer_time_limit_seconds: float = Field(default=60.0, gt=0)
    optimizer_workers: int = Field(default=1, ge=1)
    optimizer_seed: int = Field(default=0, ge=0)
    # Proving which constraints bind, after the solve (ADR 0038): a constraint left unsettled
    # when the budget runs out is reported as unproven. 0 turns the analysis off.
    optimizer_binding_deterministic_limit: float = Field(default=6.0, ge=0)
    optimizer_binding_time_limit_seconds: float = Field(default=30.0, ge=0)
    # Finding the smallest relaxation of an infeasible request (ADR 0044); only a request no
    # plan can reach every clearance target of spends it.
    optimizer_relaxation_deterministic_limit: float = Field(default=10.0, gt=0)
    optimizer_relaxation_time_limit_seconds: float = Field(default=60.0, gt=0)

    # The Monte Carlo simulation of every plan revision (ADR 0042): runs per simulation, within
    # the simulator's MIN_RUNS..MAX_RUNS, and the seed that makes it reproducible.
    simulation_runs: int = Field(default=1_000, ge=100, le=5_000)
    simulation_seed: int = Field(default=0, ge=0)

    # The Critic's risk review (ADR 0051): a plan line above this share of the plan's promo
    # spend, or a category or region above the group share when the scope has more than one,
    # is over-concentrated; cannibalisation at or above this share of a line's incremental
    # profit is heavy; a line that runs out in at least this share of simulated runs is a
    # stock-out risk.
    critic_line_spend_share: float = Field(default=0.25, gt=0, le=1)
    critic_group_spend_share: float = Field(default=0.80, gt=0, le=1)
    critic_cannibalisation_share: float = Field(default=0.50, gt=0)
    critic_stockout_probability: float = Field(default=0.20, gt=0, le=1)

    @model_validator(mode="before")
    @classmethod
    def _resolve_auto_provider(cls, values: Any) -> Any:
        if not isinstance(values, dict) or values.get("llm_provider") != "auto":
            return values
        resolved = dict(values)
        keyed = [name for name in AUTO_MODELS if _secret_text(resolved.get(f"{name}_api_key"))]
        # A key alone is enough: each keyed provider's model defaults, so the other one is
        # still the fallback (ADR 0027).
        for name in keyed:
            if not resolved.get(f"{name}_model"):
                resolved[f"{name}_model"] = AUTO_MODELS[name]
        resolved["llm_provider"] = keyed[0] if keyed else "replay"
        return resolved


AUTO_MODELS = {"openai": "gpt-4.1-mini", "anthropic": "claude-sonnet-5"}
"""The model `LLM_PROVIDER=auto` uses when only the key is set (ADR 0022, ADR 0027)."""


def _secret_text(value: object) -> str:
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    return value if isinstance(value, str) else ""
