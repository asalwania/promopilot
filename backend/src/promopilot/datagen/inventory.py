"""Weekly inventory snapshots per store and SKU, with the company-policy overstock flag."""

import numpy as np
import pandas as pd

from promopilot.datagen.config import GeneratorConfig
from promopilot.domain import CompanyPolicy


def generate_inventory(
    config: GeneratorConfig,
    products: pd.DataFrame,
    sales: pd.DataFrame,
    rng: np.random.Generator,
    policy: CompanyPolicy | None = None,
) -> pd.DataFrame:
    """Snapshot at the end of each history week: stock set as weeks of cover of recent demand.

    Each SKU is normal, overstocked (in every region, ADR 0016) or low on stock.
    """
    policy = policy or CompanyPolicy()
    settings = config.inventory
    n = len(products)
    weeks = config.history_weeks
    stores = sales["store_id"].unique()  # sales are sorted by week, store, SKU
    units = sales["units"].to_numpy(dtype=float).reshape(weeks, len(stores), n)

    window = settings.demand_window_weeks
    running = np.cumsum(np.concatenate([np.zeros((1, len(stores), n)), units]), axis=0)
    starts = np.maximum(np.arange(1, weeks + 1) - window, 0)
    lengths = (np.arange(1, weeks + 1) - starts)[:, None, None]
    weekly_demand = np.maximum((running[1:] - running[starts]) / lengths, 0.5)

    forced = products["name"].str.contains("|".join(settings.force_overstock), regex=True)
    if not settings.force_overstock:
        forced[:] = False
    n_over = max(round(settings.overstock_share * n), int(forced.sum()))
    others = rng.permutation(np.flatnonzero(~forced.to_numpy()))
    overstock = np.zeros(n, dtype=bool)
    overstock[forced.to_numpy()] = True
    overstock[others[: n_over - int(forced.sum())]] = True
    low = np.zeros(n, dtype=bool)
    remaining = others[n_over - int(forced.sum()) :]
    low[remaining[: round(settings.low_stock_share * n)]] = True

    cover = rng.uniform(*settings.normal_cover_weeks, size=n)
    cover[overstock] = rng.uniform(*settings.overstock_cover_weeks, size=int(overstock.sum()))
    cover[low] = rng.uniform(*settings.low_stock_cover_weeks, size=int(low.sum()))
    noise = np.exp(
        rng.normal(0, settings.noise_sd, (1, len(stores), n))
        + rng.normal(0, settings.noise_sd, (weeks, len(stores), n))
    )
    on_hand = np.round(cover * weekly_demand * noise)
    on_order = np.round(
        weekly_demand * rng.uniform(*settings.on_order_weeks, (weeks, len(stores), n))
    )
    on_order[:, :, overstock] = 0
    safety_stock = np.ceil(settings.safety_stock_weeks * weekly_demand)
    days_of_cover = np.round(on_hand / (weekly_demand / 7), 1)

    return pd.DataFrame(
        {
            "snapshot_week": np.repeat(np.arange(weeks), len(stores) * n),
            "store_id": np.tile(np.repeat(stores, n), weeks),
            "sku_id": np.tile(products["sku_id"].to_numpy(), weeks * len(stores)),
            "on_hand": on_hand.ravel().astype(np.int64),
            "on_order": on_order.ravel().astype(np.int64),
            "safety_stock": safety_stock.ravel().astype(np.int64),
            "is_overstock": days_of_cover.ravel() > policy.overstock_threshold_weeks * 7,
            "days_of_cover": days_of_cover.ravel(),
        }
    )
