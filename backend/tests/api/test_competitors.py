"""`GET /api/competitors/gaps` contract, over in-memory data (ADR 0031).

The same endpoint over real Postgres runs in tests/integration/test_competitors_api.py.
"""

from typing import Any

import pandas as pd
import pytest
from httpx import ASGITransport, AsyncClient

from promopilot.api.competitors import CompetitorService
from promopilot.api.main import create_app
from promopilot.domain import CompanyPolicy
from tests.offline import NoModel, offline_sessions

DEFAULT_AS_OF = 20

PRODUCTS = pd.DataFrame(
    [
        ("K1", "Atta 5kg", "Staples", "Flour", 100.0, True),
        ("K2", "Rice 5kg", "Staples", "Rice", 100.0, True),
        ("N1", "Namkeen 400g", "Snacks", "Namkeen", 50.0, False),
    ],
    columns=["sku_id", "name", "category", "subcategory", "base_price", "is_kvi"],
).assign(brand="B", pack_size="1", unit_cost=30.0)

PRICES = pd.DataFrame(
    [
        (8, "North", "K1", 90.0, True),
        (DEFAULT_AS_OF - 1, "North", "K1", 95.1, False),
        (DEFAULT_AS_OF - 1, "North", "K2", 94.9, True),
        (DEFAULT_AS_OF - 1, "South", "K2", 99.0, False),
        (DEFAULT_AS_OF - 1, "South", "N1", 45.0, True),
    ],
    columns=["week_id", "region", "sku_id", "competitor_price", "competitor_on_promo"],
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

    async def latest_competitor_prices(self, as_of_week: int) -> pd.DataFrame:
        visible = PRICES[PRICES["week_id"] < as_of_week]
        return visible.sort_values("week_id").drop_duplicates(["region", "sku_id"], keep="last")


class HealthyProbe:
    async def is_healthy(self) -> bool:
        return True


def client_for(data: InMemoryData) -> AsyncClient:
    app = create_app(
        database_probe=HealthyProbe(),
        model_status=NoModel(),
        sessions=offline_sessions(),
        competitors=CompetitorService(data, policy=CompanyPolicy()),
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def get_gaps(params: dict[str, Any], *, data: InMemoryData | None = None) -> Any:
    async with client_for(data or InMemoryData()) as client:
        return await client.get("/api/competitors/gaps", params=params)


async def test_without_filters_every_gap_at_the_default_as_of_week_widest_first() -> None:
    response = await get_gaps({})

    assert response.status_code == 200
    body = response.json()
    assert body["as_of_week"] == DEFAULT_AS_OF
    assert body["undercut_threshold"] == 0.05
    assert body["kvi_price_tolerance"] == 0.02
    assert [(g["region"], g["sku_id"], g["undercut"]) for g in body["gaps"]] == [
        ("South", "N1", False),
        ("North", "K2", True),
        ("North", "K1", False),
        ("South", "K2", False),
    ]
    k2 = body["gaps"][1]
    assert k2 == {
        "region": "North",
        "sku_id": "K2",
        "name": "Rice 5kg",
        "category": "Staples",
        "subcategory": "Rice",
        "is_kvi": True,
        "base_price": 100.0,
        "competitor_price": 94.9,
        "competitor_on_promo": True,
        "price_week": DEFAULT_AS_OF - 1,
        "cpi": pytest.approx(0.949),
        "gap": pytest.approx(0.051),
        "undercut": True,
    }


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"region": "South"}, [("South", "N1"), ("South", "K2")]),
        ({"category": "Snacks"}, [("South", "N1")]),
        ({"kvi_only": "true"}, [("North", "K2"), ("North", "K1"), ("South", "K2")]),
        ({"region": "North", "kvi_only": "true"}, [("North", "K2"), ("North", "K1")]),
        ({"as_of_week": 9}, [("North", "K1")]),
    ],
)
async def test_filters_narrow_the_gaps(
    params: dict[str, Any], expected: list[tuple[str, str]]
) -> None:
    response = await get_gaps(params)

    assert response.status_code == 200
    assert [(g["region"], g["sku_id"]) for g in response.json()["gaps"]] == expected


async def test_an_earlier_as_of_week_sees_only_the_prices_before_it() -> None:
    response = await get_gaps({"as_of_week": 9})

    [k1] = response.json()["gaps"]
    assert (k1["competitor_price"], k1["price_week"], k1["undercut"]) == (90.0, 8, True)
    assert response.json()["as_of_week"] == 9


@pytest.mark.parametrize("params", [{"region": "Mars"}, {"as_of_week": -1}, {"kvi_only": "maybe"}])
async def test_malformed_filters_are_422(params: dict[str, Any]) -> None:
    assert (await get_gaps(params)).status_code == 422


async def test_an_unknown_category_is_422_naming_it() -> None:
    response = await get_gaps({"category": "Toys"})

    assert response.status_code == 422
    assert "Toys" in response.json()["detail"]


async def test_without_loaded_data_the_default_as_of_week_is_409_saying_to_run_make_data() -> None:
    response = await get_gaps({}, data=InMemoryData(loaded=False))

    assert response.status_code == 409
    assert "make data" in response.json()["detail"]
