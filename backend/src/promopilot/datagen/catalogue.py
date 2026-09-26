"""The product catalogue: categories, subcategories, brands, pack sizes, prices, KVIs."""

import numpy as np
import pandas as pd

from promopilot.datagen.config import CatalogueConfig


def generate_products(config: CatalogueConfig, rng: np.random.Generator) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for category in config.categories:
        premium = {brand: rng.uniform(*config.brand_premium) for brand in category.brands}
        combos = [
            (sub.name, brand, pack, reference_price)
            for sub in category.subcategories
            for brand in category.brands
            for pack, reference_price in sub.packs.items()
        ]
        if config.skus_per_category > len(combos):
            raise ValueError(
                f"{category.name} has only {len(combos)} brand x pack combinations "
                f"for {config.skus_per_category} SKUs"
            )
        # Spread SKUs across subcategories first, then brands and packs within each.
        order = rng.permutation(len(combos))
        by_subcategory: dict[str, list[int]] = {}
        for index in order:
            by_subcategory.setdefault(combos[index][0], []).append(int(index))
        picked: list[int] = []
        while len(picked) < config.skus_per_category:
            for indices in by_subcategory.values():
                if indices and len(picked) < config.skus_per_category:
                    picked.append(indices.pop())
        for index in sorted(picked):
            subcategory, brand, pack, reference_price = combos[index]
            base_price = max(20.0, float(round(reference_price * premium[brand])))
            margin = rng.uniform(*category.margin)
            rows.append(
                {
                    "name": f"{brand} {subcategory} {pack}",
                    "brand": brand,
                    "category": category.name,
                    "subcategory": subcategory,
                    "pack_size": pack,
                    "base_price": base_price,
                    "unit_cost": round(base_price * (1 - margin), 2),
                }
            )
    products = pd.DataFrame(rows)
    products.insert(0, "sku_id", [f"SKU{i + 1:04d}" for i in range(len(products))])
    n_kvi = max(1, round(config.kvi_share * len(products)))
    products["is_kvi"] = False
    products.loc[rng.choice(len(products), size=n_kvi, replace=False), "is_kvi"] = True
    return products
