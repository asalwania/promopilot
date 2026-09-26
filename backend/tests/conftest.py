import json

import pytest

from promopilot.datagen import GeneratedDataset, GeneratorConfig, generate, load_config
from promopilot.models.demand import DemandHistory

LLM_ENV = ("LLM_PROVIDER", "LLM_CASSETTE_DIR", "OPENAI_API_KEY", "OPENAI_MODEL")


@pytest.fixture(autouse=True)
def no_llm_config_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """`make test` exports .env: a real key or model must never reach a test (SPEC §6)."""
    for name in LLM_ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(scope="session")
def small_config() -> GeneratorConfig:
    """A few SKUs, two regions, one year: generates in about a second (ADR 0010)."""
    return load_config(
        overrides={
            "catalogue": {"categories_limit": 3, "skus_per_category": 8},
            "regions": ["North", "South"],
            "stores_per_region": 3,
            "history_weeks": 52,
            "horizon_weeks": 12,
            "baskets": 5_000,
            "complement_pairs": 6,
        }
    )


@pytest.fixture(scope="session")
def small_dataset(small_config: GeneratorConfig) -> GeneratedDataset:
    return generate(small_config, seed=11)


@pytest.fixture(scope="session")
def default_dataset() -> GeneratedDataset:
    """The full SPEC §8.1 default world (seed 42), as `make data` produces it."""
    return generate(load_config(), seed=42)


def history_of(dataset: GeneratedDataset) -> DemandHistory:
    """The data tables as the repositories return them (JSONB decoded), with no ground truth."""
    sales = dataset.sales_weekly.copy()
    sales["segment_units"] = sales["segment_units"].map(json.loads)
    return DemandHistory(
        products=dataset.products,
        stores=dataset.stores,
        calendar=dataset.calendar,
        sales_weekly=sales,
        promotions_history=dataset.promotions_history,
        competitor_prices=dataset.competitor_prices,
    )


@pytest.fixture(scope="session")
def small_history(small_dataset: GeneratedDataset) -> DemandHistory:
    return history_of(small_dataset)
