"""generate(config, seed): the whole synthetic retail world, in memory."""

from promopilot.datagen.catalogue import generate_products
from promopilot.datagen.competitors import competitor_prices_table, generate_competitor_series
from promopilot.datagen.config import GeneratorConfig
from promopilot.datagen.dataset import GeneratedDataset
from promopilot.datagen.params import draw_ground_truth
from promopilot.datagen.promotions import generate_promotions
from promopilot.datagen.sales import generate_sales
from promopilot.datagen.streams import stream
from promopilot.datagen.truth import TrueDemand
from promopilot.datagen.world import generate_calendar, generate_stores


def generate(config: GeneratorConfig, seed: int) -> GeneratedDataset:
    """Same config and seed give identical tables and ground truth."""
    products = generate_products(config.catalogue, stream(seed, "catalogue"))
    stores = generate_stores(config, stream(seed, "stores"))
    calendar = generate_calendar(config)
    competitors = generate_competitor_series(config, products, stream(seed, "competitors"))
    truth = draw_ground_truth(
        config, products, stores, calendar, competitors, stream(seed, "demand")
    )
    promotions, scenarios = generate_promotions(config, products, truth, stream(seed, "promotions"))
    sales = generate_sales(config, TrueDemand(truth), promotions, scenarios, stream(seed, "sales"))
    return GeneratedDataset(
        config=config,
        seed=seed,
        products=products,
        stores=stores,
        calendar=calendar,
        competitor_prices=competitor_prices_table(config, products, competitors),
        promotions_history=promotions,
        sales_weekly=sales,
        ground_truth=truth,
    )
