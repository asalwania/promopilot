"""`GET /api/relations/{sku_id}`: a SKU's substitutes and complements (SPEC §10, ADR 0033)."""

import math
from datetime import UTC, datetime
from uuid import uuid4

import pandas as pd
import pytest
from httpx import ASGITransport, AsyncClient

from promopilot.api.main import create_app
from promopilot.api.relations import RelationsService
from promopilot.models.demand import DemandHistory, DemandModel
from promopilot.models.registry import ModelKind, RegisteredModel
from promopilot.models.relations import Relations
from tests.offline import NoModel, offline_sessions

ENTRY = RegisteredModel(
    model_id=uuid4(),
    kind=ModelKind.RELATIONS,
    version=2,
    trained_at=datetime(2026, 9, 26, tzinfo=UTC),
    as_of_week=52,
    metrics={"demand_version": 1.0},
    artifact_path="relations-v2.pkl",
)


class FixedRelations:
    def __init__(self, loaded: tuple[RegisteredModel, Relations] | None) -> None:
        self.loaded = loaded

    async def get(self) -> tuple[RegisteredModel, Relations] | None:
        return self.loaded


class Catalogue:
    def __init__(self, products: pd.DataFrame) -> None:
        self._products = products

    async def products(self) -> pd.DataFrame:
        return self._products


class HealthyProbe:
    async def is_healthy(self) -> bool:
        return True


def client_for(
    loaded: tuple[RegisteredModel, Relations] | None, products: pd.DataFrame
) -> AsyncClient:
    app = create_app(
        database_probe=HealthyProbe(),
        model_status=NoModel(),
        sessions=offline_sessions(),
        relations=RelationsService(FixedRelations(loaded), Catalogue(products)),
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(scope="module")
def fitted(small_models: tuple[DemandModel, Relations]) -> Relations:
    return small_models[1]


async def test_a_skus_relations_follow_the_contract(
    fitted: Relations, small_history: DemandHistory
) -> None:
    sku_ids = sorted(small_history.products["sku_id"])
    sku_id = next(
        sku
        for sku in sku_ids
        if not fitted.substitutes(sku).empty and not fitted.complements(sku).empty
    )
    async with client_for((ENTRY, fitted), small_history.products) as client:
        response = await client.get(f"/api/relations/{sku_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["model"] == {
        "model_id": str(ENTRY.model_id),
        "version": 2,
        "as_of_week": 52,
    }
    assert body["sku_id"] == sku_id
    substitutes = fitted.substitutes(sku_id)
    assert [s["sku_id"] for s in body["substitutes"]] == list(substitutes["sku_id"])
    assert set(body["substitutes"][0]) == {"sku_id", "theta", "std_error", "q_value"}
    complements = fitted.complements(sku_id)
    assert [c["sku_id"] for c in body["complements"]] == list(complements["sku_id"])
    assert set(body["complements"][0]) == {"sku_id", "lift", "support", "theta", "std_error"}
    for complement, theta in zip(body["complements"], complements["theta"], strict=True):
        assert (complement["theta"] is None) == math.isnan(theta)


async def test_an_unknown_sku_is_404(fitted: Relations, small_history: DemandHistory) -> None:
    async with client_for((ENTRY, fitted), small_history.products) as client:
        response = await client.get("/api/relations/NOPE-1")

    assert response.status_code == 404
    assert "NOPE-1" in response.json()["detail"]


async def test_no_relations_model_is_503(small_history: DemandHistory) -> None:
    sku_id = str(small_history.products["sku_id"].iloc[0])
    async with client_for(None, small_history.products) as client:
        response = await client.get(f"/api/relations/{sku_id}")

    assert response.status_code == 503
    assert "relations model" in response.json()["detail"]


def test_the_openapi_contract_documents_the_endpoint(small_history: DemandHistory) -> None:
    app = create_app(
        database_probe=HealthyProbe(),
        model_status=NoModel(),
        sessions=offline_sessions(),
        relations=RelationsService(FixedRelations(None), Catalogue(small_history.products)),
    )

    operation = app.openapi()["paths"]["/api/relations/{sku_id}"]["get"]

    assert set(operation["responses"]) >= {"200", "404", "503"}
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema == {"$ref": "#/components/schemas/RelationsResponse"}
