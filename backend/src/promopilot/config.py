"""Runtime configuration, read from environment variables (see .env.example)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    database_url: str = "postgresql+asyncpg://promopilot:promopilot@localhost:5432/promopilot"
