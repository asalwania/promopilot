"""Runtime configuration, read from environment variables (see .env.example)."""

from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    database_url: str = "postgresql+asyncpg://promopilot:promopilot@localhost:5432/promopilot"

    # Trained model artifacts (ADR 0023); the registry rows hold paths relative to it.
    # Relative paths are from backend/.
    model_dir: Path = Path("../models")

    # LLM layer (ADR 0001, ADR 0019). `replay` needs no key; relative paths are from backend/.
    llm_provider: Literal["openai", "anthropic", "replay", "fake"] = "replay"
    llm_cassette_dir: Path = Path("cassettes")
    openai_api_key: SecretStr | None = None
    openai_model: str | None = None
