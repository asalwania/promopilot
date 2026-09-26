"""Narrowing the catalogue to the regions, categories and SKUs a data-tool call names."""

from collections.abc import Sequence

import pandas as pd

from promopilot.agents.tools.registry import ToolCallError, ToolErrorDetail
from promopilot.domain import Region


def in_scope(
    products: pd.DataFrame,
    known_regions: Sequence[str],
    *,
    regions: Sequence[Region] | None,
    categories: Sequence[str] | None,
    sku_ids: Sequence[str] | None,
) -> tuple[pd.DataFrame, list[Region]]:
    """The named products (all when none are named) and regions, in catalogue and enum order.

    A name the data lacks is a `ToolCallError` that locates it, e.g. `categories.1`.
    """
    details = [
        ToolErrorDetail(loc=f"regions.{n}", message=f"no data for region {region.value}")
        for n, region in enumerate(regions or ())
        if region.value not in known_regions
    ]
    details += [
        ToolErrorDetail(loc=f"categories.{n}", message=f"no category named {category}")
        for n, category in enumerate(categories or ())
        if category not in set(products["category"])
    ]
    details += [
        ToolErrorDetail(loc=f"sku_ids.{n}", message=f"no SKU with id {sku_id}")
        for n, sku_id in enumerate(sku_ids or ())
        if sku_id not in set(products["sku_id"])
    ]
    if details:
        raise ToolCallError("invalid_input", "the call names things the data lacks", details)
    chosen = products.sort_values("sku_id")
    if categories is not None:
        chosen = chosen[chosen["category"].isin(categories)]
    if sku_ids is not None:
        chosen = chosen[chosen["sku_id"].isin(sku_ids)]
    named = set(regions) if regions is not None else {Region(r) for r in known_regions}
    return chosen, [region for region in Region if region in named]
