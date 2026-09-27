import json

import pytest

from promopilot.agents.tools.inventory_status import pooled_stock
from promopilot.datagen import GeneratedDataset, GeneratorConfig, generate, load_config
from promopilot.domain import CompanyPolicy, PlanningRequest, PromoWindow, Region, Scope
from promopilot.models import demand, relations
from promopilot.models.demand import DemandHistory, DemandModel
from promopilot.models.relations import Relations
from promopilot.models.training import DEFAULT_SEED
from promopilot.optimizer import OptionContext

LLM_ENV = ("LLM_PROVIDER", "LLM_CASSETTE_DIR", "OPENAI_API_KEY", "OPENAI_MODEL")


@pytest.fixture(autouse=True)
def no_llm_config_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """`make test` exports .env: a real key or model must never reach a test (SPEC §6)."""
    for name in LLM_ENV:
        monkeypatch.delenv(name, raising=False)


SMALL_AS_OF = 52
"""The first week after the small world's 52 history weeks."""

SMALL_OVERRIDES = {
    "catalogue": {"categories_limit": 3, "skus_per_category": 8},
    "regions": ["North", "South"],
    "stores_per_region": 3,
    "history_weeks": 52,
    "horizon_weeks": 12,
    "baskets": 5_000,
    "complement_pairs": 6,
}


@pytest.fixture(scope="session")
def small_config() -> GeneratorConfig:
    """A few SKUs, two regions, one year: generates in about a second (ADR 0010)."""
    return load_config(overrides=SMALL_OVERRIDES)


@pytest.fixture(scope="session")
def small_dataset(small_config: GeneratorConfig) -> GeneratedDataset:
    return generate(small_config, seed=11)


MEDIUM_OVERRIDES = {
    "catalogue": {"categories_limit": 4, "skus_per_category": 8},
    "regions": ["North", "South", "East", "West"],
    "stores_per_region": 3,
    "history_weeks": 104,
    "horizon_weeks": 12,
    "baskets": 5_000,
    "complement_pairs": 8,
}
"""Enough promotions per SKU to measure elasticity recovery (marker `model`, ADR 0010)."""


RELATIONS_OVERRIDES = {
    "catalogue": {"categories_limit": 4, "skus_per_category": 24},
    "regions": ["North", "South", "East", "West"],
    "stores_per_region": 3,
    "history_weeks": 104,
    "horizon_weeks": 12,
    "baskets": 20_000,
    "complement_pairs": 20,
}
"""Enough within-subcategory pairs and baskets to measure relation detection (ADR 0029)."""


@pytest.fixture(scope="session")
def medium_dataset() -> GeneratedDataset:
    return generate(load_config(overrides=MEDIUM_OVERRIDES), seed=5)


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


@pytest.fixture(scope="session")
def small_models(
    small_dataset: GeneratedDataset, small_history: DemandHistory
) -> tuple[DemandModel, Relations]:
    """Demand, then relations, fitted on the small world as of its first future week."""
    model = demand.fit(small_history, as_of_week=SMALL_AS_OF, seed=7)
    return model, relations.fit(
        small_history, small_dataset.baskets, model, as_of_week=SMALL_AS_OF, seed=7
    )


DEMO_AS_OF = 104

DEMO_BRIEF = PlanningRequest(
    as_of_week=DEMO_AS_OF,
    scope=Scope(regions=(Region.NORTH, Region.WEST), categories=("Snacks", "Beverages")),
    promo_window=PromoWindow(start_week=108, end_week=109),
    marketing_budget=200_000.0,
)
"""The demo brief's scope, Diwali window and ₹2 lakh budget (ADR 0036, ADR 0037)."""


@pytest.fixture(scope="session")
def demo_context(default_dataset: GeneratedDataset) -> OptionContext:
    """The seed-42 world fitted as `make train` fits it, with its pooled stock (marker `model`)."""
    history = history_of(default_dataset)
    model = demand.fit(history, DEMO_AS_OF, DEFAULT_SEED)
    found = relations.fit(
        history, default_dataset.baskets, model, as_of_week=DEMO_AS_OF, seed=DEFAULT_SEED
    )
    inventory = default_dataset.inventory
    policy = CompanyPolicy()
    return OptionContext(
        demand_model=model,
        relations=found,
        products=default_dataset.products,
        stock=pooled_stock(
            inventory[inventory["snapshot_week"] == DEMO_AS_OF - 1],
            default_dataset.stores,
            policy,
        ),
        policy=policy,
    )
