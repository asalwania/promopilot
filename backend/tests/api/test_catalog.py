"""`GET /api/catalog/products`, `/api/catalog/regions` and `/api/inventory` contract (ADR 0034).

Over in-memory data; the same endpoints over real Postgres run in
tests/integration/test_catalog_api.py.
"""

from typing import Any

import pandas as pd
import pytest
from httpx import ASGITransport, AsyncClient

from promopilot.api.catalog import CatalogService
from promopilot.api.main import create_app
from promopilot.domain import CompanyPolicy
from tests.offline import NoModel, offline_sessions

DEFAULT_AS_OF = 20

PRODUCTS = pd.DataFrame(
    [
        ("K1", "Atta 5kg", "Aashirvaad", "Staples", "Flour", "5kg", 250.0, 200.0, True),
        ("N1", "Namkeen 400g", "Haldiram", "Snacks", "Namkeen", "400g", 90.0, 60.0, False),
        ("C1", "Cola 2L", "Thums Up", "Beverages", "Cola", "2L", 95.0, 70.0, False),
    ],
    columns=[
        "sku_id",
        "name",
        "brand",
        "category",
        "subcategory",
        "pack_size",
        "base_price",
        "unit_cost",
        "is_kvi",
    ],
).sort_values("sku_id")

SKUS = list(PRODUCTS["sku_id"])

MIX = {"Value Seekers": 0.4, "Families": 0.3, "Premium": 0.2, "Young Urban": 0.1}

STORES = pd.DataFrame(
    [
        ("S01", "North", "Delhi", MIX),
        ("S02", "North", "Jaipur", MIX),
        ("S03", "South", "Chennai", MIX),
    ],
    columns=["store_id", "region", "city", "segment_mix"],
)


def snapshot(week: int, rows: list[tuple[str, str, int, int, int, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        rows, columns=["store_id", "sku_id", "on_hand", "on_order", "safety_stock", "days_of_cover"]
    ).assign(snapshot_week=week)


INVENTORY = pd.concat(
    [
        # A pooled region's cover is sum(on hand) / sum(on hand / cover) (ADR 0032).
        snapshot(
            DEFAULT_AS_OF - 1,
            [
                ("S01", "K1", 100, 5, 10, 100.0),  # 1 unit a day
                ("S02", "K1", 20, 0, 10, 10.0),  # 2 units a day: North K1 is 120 / 3 = 40 days
                ("S01", "N1", 70, 0, 5, 70.0),
                ("S02", "N1", 0, 12, 5, 0.0),  # North N1 is 70 / 1 = 70 days: overstocked
                ("S01", "C1", 30, 0, 5, 15.0),
                ("S02", "C1", 30, 0, 5, 15.0),
                ("S03", "K1", 50, 0, 10, 25.0),
                ("S03", "N1", 90, 0, 5, 90.0),  # overstocked
                ("S03", "C1", 10, 0, 5, 5.0),
            ],
        ),
        snapshot(8, [(store, sku, 1, 0, 0, 1.0) for store in STORES["store_id"] for sku in SKUS]),
    ]
)


class InMemoryData:
    def __init__(self, *, loaded: bool = True) -> None:
        self.loaded = loaded

    async def default_as_of_week(self) -> int:
        if not self.loaded:
            raise LookupError("no sales history is loaded; run `make data`")
        return DEFAULT_AS_OF

    async def products(self) -> pd.DataFrame:
        return PRODUCTS

    async def stores(self) -> pd.DataFrame:
        return STORES

    async def inventory(self, as_of_week: int) -> pd.DataFrame:
        frame = INVENTORY[INVENTORY["snapshot_week"] == as_of_week - 1]
        if frame.empty:
            raise LookupError(f"no inventory snapshot for the end of week {as_of_week - 1}")
        return frame


class HealthyProbe:
    async def is_healthy(self) -> bool:
        return True


async def get(path: str, params: dict[str, Any] | None = None, *, loaded: bool = True) -> Any:
    app = create_app(
        database_probe=HealthyProbe(),
        model_status=NoModel(),
        sessions=offline_sessions(),
        catalog=CatalogService(InMemoryData(loaded=loaded), policy=CompanyPolicy()),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(path, params=params or {})


async def test_products_lists_the_whole_catalogue_in_sku_order() -> None:
    response = await get("/api/catalog/products")

    assert response.status_code == 200
    products = response.json()["products"]
    assert [p["sku_id"] for p in products] == ["C1", "K1", "N1"]
    assert products[1] == {
        "sku_id": "K1",
        "name": "Atta 5kg",
        "brand": "Aashirvaad",
        "category": "Staples",
        "subcategory": "Flour",
        "pack_size": "5kg",
        "base_price": 250.0,
        "unit_cost": 200.0,
        "is_kvi": True,
    }


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"category": "Snacks"}, ["N1"]),
        ({"kvi_only": "true"}, ["K1"]),
        ({"category": "Snacks", "kvi_only": "true"}, []),
    ],
)
async def test_products_filter_by_category_and_kvi(
    params: dict[str, Any], expected: list[str]
) -> None:
    response = await get("/api/catalog/products", params)

    assert response.status_code == 200
    assert [p["sku_id"] for p in response.json()["products"]] == expected


async def test_an_unknown_product_category_is_422_naming_it() -> None:
    response = await get("/api/catalog/products", {"category": "Toys"})

    assert response.status_code == 422
    assert "Toys" in response.json()["detail"]


async def test_regions_list_their_stores_with_segment_mix_in_region_order() -> None:
    response = await get("/api/catalog/regions")

    assert response.status_code == 200
    assert response.json() == {
        "regions": [
            {
                "region": "North",
                "stores": [
                    {"store_id": "S01", "city": "Delhi", "segment_mix": MIX},
                    {"store_id": "S02", "city": "Jaipur", "segment_mix": MIX},
                ],
            },
            {
                "region": "South",
                "stores": [{"store_id": "S03", "city": "Chennai", "segment_mix": MIX}],
            },
        ]
    }


async def test_inventory_pools_each_region_at_the_default_as_of_week_with_names() -> None:
    response = await get("/api/inventory")

    assert response.status_code == 200
    body = response.json()
    assert (body["as_of_week"], body["snapshot_week"]) == (DEFAULT_AS_OF, DEFAULT_AS_OF - 1)
    assert body["overstock_threshold_days"] == 56
    assert [(s["sku_id"], s["region"]) for s in body["statuses"]] == [
        ("C1", "North"),
        ("C1", "South"),
        ("K1", "North"),
        ("K1", "South"),
        ("N1", "North"),
        ("N1", "South"),
    ]
    k1_north = body["statuses"][2]
    assert k1_north == {
        "sku_id": "K1",
        "name": "Atta 5kg",
        "category": "Staples",
        "region": "North",
        "on_hand": 120,
        "safety_stock": 20,
        "on_order": 5,
        "available_stock": 100,
        "days_of_cover": pytest.approx(40.0),
        "is_overstock": False,
    }
    n1_north = body["statuses"][4]
    assert (n1_north["days_of_cover"], n1_north["is_overstock"]) == (pytest.approx(70.0), True)


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"region": "South"}, [("C1", "South"), ("K1", "South"), ("N1", "South")]),
        ({"category": "Snacks"}, [("N1", "North"), ("N1", "South")]),
        ({"overstocked_only": "true"}, [("N1", "North"), ("N1", "South")]),
        ({"region": "North", "overstocked_only": "true"}, [("N1", "North")]),
    ],
)
async def test_inventory_filters(params: dict[str, Any], expected: list[tuple[str, str]]) -> None:
    response = await get("/api/inventory", params)

    assert response.status_code == 200
    assert [(s["sku_id"], s["region"]) for s in response.json()["statuses"]] == expected


async def test_inventory_at_an_earlier_as_of_week_reads_the_snapshot_before_it() -> None:
    response = await get("/api/inventory", {"as_of_week": 9, "region": "South"})

    assert response.status_code == 200
    body = response.json()
    assert (body["as_of_week"], body["snapshot_week"]) == (9, 8)
    assert {s["on_hand"] for s in body["statuses"]} == {1}


@pytest.mark.parametrize(
    "params",
    [{"region": "Mars"}, {"as_of_week": -1}, {"overstocked_only": "maybe"}, {"category": "Toys"}],
)
async def test_malformed_inventory_filters_are_422(params: dict[str, Any]) -> None:
    assert (await get("/api/inventory", params)).status_code == 422


async def test_a_region_without_stores_is_422_naming_it() -> None:
    response = await get("/api/inventory", {"region": "East"})

    assert response.status_code == 422
    assert "East" in response.json()["detail"]


async def test_inventory_without_loaded_data_is_409_saying_to_run_make_data() -> None:
    response = await get("/api/inventory", loaded=False)

    assert response.status_code == 409
    assert "make data" in response.json()["detail"]


async def test_inventory_at_a_week_without_a_snapshot_is_409_naming_it() -> None:
    response = await get("/api/inventory", {"as_of_week": 500})

    assert response.status_code == 409
    assert "499" in response.json()["detail"]
