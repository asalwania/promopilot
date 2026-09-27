"""`generate_candidates` through the tool registry: a summary for the planner, the full set
kept for the optimiser (ADR 0035)."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from promopilot.agents.tools import ToolError, ToolOk, ToolRegistry
from promopilot.agents.tools.as_of import fixed_as_of_week
from promopilot.agents.tools.generate_candidates import (
    MAX_TOP,
    GenerateCandidatesInput,
    GenerateCandidatesOutput,
    generate_candidates_tool,
)
from promopilot.datagen import GeneratedDataset
from promopilot.domain import CompanyPolicy, Mechanism
from promopilot.models.demand import DemandHistory, DemandModel
from promopilot.models.registry import ModelKind, RegisteredModel
from promopilot.models.relations import Relations
from promopilot.optimizer import CandidateStore
from tests.conftest import SMALL_AS_OF
from tests.unit.agents.fakes import InMemoryRetailData


class Fixed[T]:
    def __init__(self, loaded: tuple[RegisteredModel, T] | None) -> None:
        self.loaded = loaded

    async def get(self) -> tuple[RegisteredModel, T] | None:
        return self.loaded


def entry(kind: ModelKind, version: int) -> RegisteredModel:
    return RegisteredModel(
        model_id=uuid4(),
        kind=kind,
        version=version,
        trained_at=datetime(2026, 9, 26, tzinfo=UTC),
        as_of_week=SMALL_AS_OF,
        metrics={},
        artifact_path=f"{kind.value}-v{version}.pkl",
    )


@pytest.fixture
def store() -> CandidateStore:
    return CandidateStore()


def build(
    small_models: tuple[DemandModel, Relations],
    small_dataset: GeneratedDataset,
    store: CandidateStore,
    *,
    demand: bool = True,
    relations: bool = True,
) -> ToolRegistry:
    model, found = small_models
    return ToolRegistry(
        [
            generate_candidates_tool(
                Fixed((entry(ModelKind.DEMAND, 3), model) if demand else None),
                Fixed((entry(ModelKind.RELATIONS, 2), found) if relations else None),
                InMemoryRetailData(small_dataset),
                fixed_as_of_week(SMALL_AS_OF),
                policy=CompanyPolicy(),
                store=store,
            )
        ]
    )


@pytest.fixture
def tools(
    small_models: tuple[DemandModel, Relations],
    small_dataset: GeneratedDataset,
    store: CandidateStore,
) -> ToolRegistry:
    return build(small_models, small_dataset, store)


def arguments(small_history: DemandHistory, **changes: Any) -> dict[str, Any]:
    category = sorted(small_history.products["category"].unique())[0]
    request = {
        "as_of_week": SMALL_AS_OF,
        "scope": {"regions": ["North"], "categories": [category]},
        "promo_window": {"start_week": SMALL_AS_OF + 1, "end_week": SMALL_AS_OF + 2},
        "marketing_budget": 200_000.0,
    }
    return {"request": request | changes.pop("request", {}), **changes}


def test_the_registry_lists_generate_candidates_with_its_schemas(tools: ToolRegistry) -> None:
    [spec] = tools.specs()

    assert spec.name == "generate_candidates"
    assert spec.input_schema == GenerateCandidatesInput.model_json_schema()
    assert spec.output_schema == GenerateCandidatesOutput.model_json_schema(mode="serialization")


async def test_a_call_returns_a_summary_and_stores_the_full_set(
    tools: ToolRegistry, store: CandidateStore, small_history: DemandHistory
) -> None:
    result = await tools.call("generate_candidates", arguments(small_history))

    assert isinstance(result, ToolOk), result
    output = result.output
    assert isinstance(output, GenerateCandidatesOutput)
    GenerateCandidatesOutput.model_validate(output.model_dump(mode="json"))
    stored = store.get(output.candidate_set_id)
    assert stored is not None
    assert stored.request.as_of_week == SMALL_AS_OF
    options = stored.options
    assert output.kept == len(options.lines) > 0
    assert output.enumerated == output.kept + sum(row.count for row in output.pruned)
    assert {row.reason for row in output.pruned} == set(options.pruned)
    assert sum(row.count for row in output.by_region_and_mechanism) == output.kept
    assert output.demand_model.version == 3
    assert output.relations_model.version == 2
    assert output.as_of_week == SMALL_AS_OF
    # The top options by value, best first, straight from the stored table.
    assert len(output.top) == MAX_TOP
    values = [row.value for row in output.top]
    assert values == sorted(values, reverse=True)
    assert values[0] == pytest.approx(options.table["value"].max())
    best = int(options.table["value"].to_numpy().argmax())
    assert output.top[0].option == options.lines[best]
    assert output.top[0].p90_units == pytest.approx(options.table["p90_units"].iloc[best])


async def test_the_planner_can_narrow_the_mechanisms(
    tools: ToolRegistry, store: CandidateStore, small_history: DemandHistory
) -> None:
    result = await tools.call(
        "generate_candidates", arguments(small_history, mechanisms=["PCT_OFF", "FIXED_PRICE"])
    )

    assert isinstance(result, ToolOk), result
    assert isinstance(result.output, GenerateCandidatesOutput)
    stored = store.get(result.output.candidate_set_id)
    assert stored is not None
    assert {line.mechanism for line in stored.options.lines} == {
        Mechanism.PCT_OFF,
        Mechanism.FIXED_PRICE,
    }


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"request": {"as_of_week": SMALL_AS_OF - 1}}, "as-of week"),
        ({"sku_ids": ["NOPE"]}, "scope"),
        ({"request": {"scope": {"regions": ["North"], "categories": ["Nope"]}}}, "data lacks"),
    ],
)
async def test_calls_the_data_cannot_answer_are_invalid_input(
    tools: ToolRegistry, small_history: DemandHistory, changes: dict[str, Any], message: str
) -> None:
    result = await tools.call("generate_candidates", arguments(small_history, **changes))

    assert isinstance(result, ToolError)
    assert result.code == "invalid_input"
    assert message in result.message


async def test_a_sku_outside_the_requests_scope_is_invalid_input(
    tools: ToolRegistry, small_history: DemandHistory
) -> None:
    products = small_history.products
    category = sorted(products["category"].unique())[0]
    outside = str(products.loc[products["category"] != category, "sku_id"].iloc[0])

    result = await tools.call("generate_candidates", arguments(small_history, sku_ids=[outside]))

    assert isinstance(result, ToolError)
    assert result.code == "invalid_input"
    assert outside in result.message


async def test_schema_violations_are_invalid_input(
    tools: ToolRegistry, small_history: DemandHistory
) -> None:
    result = await tools.call("generate_candidates", arguments(small_history, budget=5))

    assert isinstance(result, ToolError)
    assert result.code == "invalid_input"


@pytest.mark.parametrize("missing", ["demand", "relations"])
async def test_a_missing_model_is_model_unavailable(
    small_models: tuple[DemandModel, Relations],
    small_dataset: GeneratedDataset,
    small_history: DemandHistory,
    store: CandidateStore,
    missing: str,
) -> None:
    tools = build(small_models, small_dataset, store, **{missing: False})

    result = await tools.call("generate_candidates", arguments(small_history))

    assert isinstance(result, ToolError)
    assert result.code == "model_unavailable"


async def test_undercut_kvis_get_price_match_options_listed_for_the_planner(
    tools: ToolRegistry, store: CandidateStore, small_history: DemandHistory
) -> None:
    categories = sorted(small_history.products["category"].unique())
    scope = {"regions": ["North", "South"], "categories": categories}

    result = await tools.call(
        "generate_candidates", arguments(small_history, request={"scope": scope})
    )

    assert isinstance(result, ToolOk), result
    assert isinstance(result.output, GenerateCandidatesOutput)
    stored = store.get(result.output.candidate_set_id)
    assert stored is not None
    matches = stored.options.price_matches
    assert matches, "the small world has undercut KVIs"
    assert [
        (m.sku_id, m.region, m.depth_pct, m.competitor_price) for m in result.output.price_matches
    ] == [(m.sku_id, m.region, m.depth_pct, m.competitor_price) for m in matches]
    # The stored facts carry each KVI's competitor price for the KVI price tolerance.
    first = matches[0]
    assert stored.facts.sku(first.sku_id, first.region).competitor_price == first.competitor_price


async def test_a_clearance_target_outside_the_scope_is_invalid_input(
    tools: ToolRegistry, small_history: DemandHistory
) -> None:
    products = small_history.products
    category = sorted(products["category"].unique())[0]
    outside = str(products.loc[products["category"] != category, "sku_id"].iloc[0])
    targets = [{"sku_id": outside, "sell_through": 0.5}]

    result = await tools.call(
        "generate_candidates", arguments(small_history, request={"clearance_targets": targets})
    )

    assert isinstance(result, ToolError)
    assert result.code == "invalid_input"
    assert outside in result.message
