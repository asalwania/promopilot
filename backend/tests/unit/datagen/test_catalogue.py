from promopilot.datagen import GeneratedDataset, GeneratorConfig, generate, load_config


def test_default_config_has_the_spec_section_8_1_catalogue() -> None:
    config = load_config()

    assert config.seed == 42
    assert [category.name for category in config.catalogue.categories] == [
        "Snacks",
        "Beverages",
        "Dairy",
        "Personal Care",
        "Home Care",
        "Staples",
        "Frozen",
        "Bakery",
    ]
    assert config.catalogue.skus_per_category == 25
    assert all(3 <= len(c.subcategories) <= 4 for c in config.catalogue.categories)
    assert all(2 <= len(c.brands) <= 4 for c in config.catalogue.categories)


def test_catalogue_follows_the_config(small_dataset: GeneratedDataset) -> None:
    products = small_dataset.products
    config = small_dataset.config

    assert len(products) == len(config.catalogue.categories) * config.catalogue.skus_per_category
    assert products["sku_id"].is_unique
    assert products["name"].is_unique
    for category in config.catalogue.categories:
        rows = products[products["category"] == category.name]
        assert set(rows["subcategory"]) <= {s.name for s in category.subcategories}
        assert set(rows["brand"]) <= set(category.brands)


def test_every_sku_sells_above_cost_at_a_positive_price(small_dataset: GeneratedDataset) -> None:
    products = small_dataset.products

    assert (products["unit_cost"] > 0).all()
    assert (products["base_price"] > products["unit_cost"]).all()


def test_some_but_not_all_skus_are_kvis(small_dataset: GeneratedDataset) -> None:
    assert 0 < small_dataset.products["is_kvi"].sum() < len(small_dataset.products)


def test_config_overrides_replace_defaults() -> None:
    config = load_config(overrides={"seed": 7, "catalogue": {"skus_per_category": 4}})

    assert config.seed == 7
    assert config.catalogue.skus_per_category == 4
    assert len(config.catalogue.categories) == 8


def test_generate_is_reachable_with_an_explicit_seed(small_config: GeneratorConfig) -> None:
    dataset = generate(small_config, seed=3)

    assert dataset.seed == 3


def test_default_catalogue_has_200_skus_across_8_categories() -> None:
    dataset = generate(load_config(), seed=42)

    assert len(dataset.products) == 200
    assert dataset.products.groupby("category").size().eq(25).all()
    assert dataset.products["base_price"].min() >= 20
