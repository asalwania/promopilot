import pytest

from promopilot.datagen import GeneratedDataset, GeneratorConfig, generate, load_config


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
