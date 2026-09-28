"""Runtime configuration, read from environment variables (see .env.example)."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr
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
    llm_provider: Literal["openai", "anthropic", "replay", "fake"] = "replay"
    llm_cassette_dir: Path = Path("cassettes")
    openai_api_key: SecretStr | None = None
    openai_model: str | None = None
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str | None = None
    # Per-model prices (LLM_PRICES, JSON) and the rupee rate for per-session cost (ADR 0027).
    llm_prices: dict[str, ModelPrice] = Field(default_factory=lambda: dict(DEFAULT_LLM_PRICES))
    usd_inr_rate: float = Field(default=96.0, gt=0)

    # The live trace (ADR 0047): how often an open SSE stream looks for new trace events, in
    # seconds, and whether logs are JSON lines (`json`) or readable text (`console`).
    trace_poll_interval_s: float = Field(default=0.5, gt=0, le=10)
    log_format: Literal["json", "console"] = "json"

    # The CP-SAT optimiser (ADR 0036). One worker and a fixed seed give the same plan for the
    # same input whenever the solver proves optimality within the time limit; more workers
    # interleave their search deterministically.
    optimizer_time_limit_seconds: float = Field(default=10.0, gt=0)
    optimizer_workers: int = Field(default=1, ge=1)
    optimizer_seed: int = Field(default=0, ge=0)
    # Wall-clock seconds for proving which constraints bind, after the solve (ADR 0038). A
    # constraint left unsettled when the time runs out is reported as unproven.
    optimizer_binding_time_limit_seconds: float = Field(default=8.0, ge=0)
    # Wall-clock seconds for finding the smallest relaxation of an infeasible request (ADR
    # 0044); only a request no plan can reach every clearance target of spends them.
    optimizer_relaxation_time_limit_seconds: float = Field(default=10.0, gt=0)

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
