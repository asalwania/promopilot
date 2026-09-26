"""`get_relations` through the tool registry: substitutes and complements for the planner."""

import math
from datetime import UTC, datetime
from uuid import uuid4

import pandas as pd
import pytest

from promopilot.agents.tools import ToolError, ToolOk, ToolRegistry
from promopilot.agents.tools.get_relations import (
    GetRelationsInput,
    GetRelationsOutput,
    get_relations_tool,
)
from promopilot.models.demand import DemandHistory, DemandModel
from promopilot.models.registry import ModelKind, RegisteredModel
from promopilot.models.relations import Relations
from tests.conftest import SMALL_AS_OF

AS_OF = SMALL_AS_OF


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


@pytest.fixture(scope="module")
def fitted(small_models: tuple[DemandModel, Relations]) -> Relations:
    return small_models[1]


@pytest.fixture(scope="module")
def entry(fitted: Relations) -> RegisteredModel:
    return RegisteredModel(
        model_id=uuid4(),
        kind=ModelKind.RELATIONS,
        version=4,
        trained_at=datetime(2026, 9, 26, tzinfo=UTC),
        as_of_week=AS_OF,
        metrics={"demand_version": 2.0},
        artifact_path="relations-v4.pkl",
    )


@pytest.fixture
def tools(entry: RegisteredModel, fitted: Relations, small_history: DemandHistory) -> ToolRegistry:
    return ToolRegistry(
        [get_relations_tool(FixedRelations((entry, fitted)), Catalogue(small_history.products))]
    )


def test_the_registry_lists_get_relations_with_its_schemas(tools: ToolRegistry) -> None:
    [spec] = tools.specs()

    assert spec.name == "get_relations"
    assert spec.input_schema == GetRelationsInput.model_json_schema()
    assert spec.output_schema == GetRelationsOutput.model_json_schema(mode="serialization")
    assert spec.input_schema["properties"]["sku_ids"]["maxItems"] == 50
    assert spec.input_schema["properties"]["sku_ids"]["minItems"] == 1


async def test_schema_valid_input_gives_the_models_relations_per_sku(
    tools: ToolRegistry, entry: RegisteredModel, fitted: Relations, small_history: DemandHistory
) -> None:
    sku_ids = sorted(small_history.products["sku_id"])
    with_complement = next(sku for sku in sku_ids if not fitted.complements(sku).empty)
    with_substitute = next(sku for sku in sku_ids if not fitted.substitutes(sku).empty)

    result = await tools.call("get_relations", {"sku_ids": [with_substitute, with_complement]})

    assert isinstance(result, ToolOk)
    output = GetRelationsOutput.model_validate(result.model_dump(mode="json")["output"])
    assert output.model.model_id == entry.model_id
    assert output.model.version == 4
    assert output.model.as_of_week == AS_OF
    assert [one.sku_id for one in output.relations] == [with_substitute, with_complement]
    substitutes = fitted.substitutes(with_substitute)
    got = output.relations[0].substitutes
    assert [s.sku_id for s in got] == list(substitutes["sku_id"])
    assert [s.theta for s in got] == pytest.approx(list(substitutes["theta"]))
    assert [s.q_value for s in got] == pytest.approx(list(substitutes["q_value"]))
    complements = fitted.complements(with_complement)
    got_complements = output.relations[1].complements
    assert [c.sku_id for c in got_complements] == list(complements["sku_id"])
    assert [c.lift for c in got_complements] == pytest.approx(list(complements["lift"]))
    for complement, theta in zip(got_complements, complements["theta"], strict=True):
        # A theta that is not estimable is null, never NaN, in what the LLM reads.
        assert (complement.theta is None) == math.isnan(theta)


async def test_an_unknown_sku_is_invalid_input(tools: ToolRegistry) -> None:
    result = await tools.call("get_relations", {"sku_ids": ["NOPE-1"]})

    assert isinstance(result, ToolError)
    assert result.code == "invalid_input"
    assert "NOPE-1" in result.message


async def test_schema_violations_are_invalid_input(tools: ToolRegistry) -> None:
    empty = await tools.call("get_relations", {"sku_ids": []})
    extra = await tools.call("get_relations", {"sku_ids": ["X"], "as_of_week": 3})

    assert isinstance(empty, ToolError)
    assert empty.code == "invalid_input"
    assert isinstance(extra, ToolError)
    assert extra.code == "invalid_input"


async def test_no_relations_model_is_model_unavailable(small_history: DemandHistory) -> None:
    tools = ToolRegistry(
        [get_relations_tool(FixedRelations(None), Catalogue(small_history.products))]
    )

    result = await tools.call("get_relations", {"sku_ids": ["X"]})

    assert isinstance(result, ToolError)
    assert result.code == "model_unavailable"
