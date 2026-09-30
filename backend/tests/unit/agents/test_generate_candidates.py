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
from promopilot.domain import CompanyPolicy, Mechanism, TargetSegment
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


def entry(kind: ModelKind, version: int, as_of_week: int = SMALL_AS_OF) -> RegisteredModel:
    return RegisteredModel(
        model_id=uuid4(),
        kind=kind,
        version=version,
        trained_at=datetime(2026, 9, 26, tzinfo=UTC),
        as_of_week=as_of_week,
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
    demand_version: int = 3,
    demand_as_of_week: int = SMALL_AS_OF,
) -> ToolRegistry:
    model, found = small_models
    demand_entry = entry(ModelKind.DEMAND, demand_version, demand_as_of_week)
    return ToolRegistry(
        [
            generate_candidates_tool(
                Fixed((demand_entry, model) if demand else None),
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


async def test_narrowing_never_limits_a_clearance_target_and_the_summary_says_so(
    tools: ToolRegistry, store: CandidateStore, small_history: DemandHistory
) -> None:
    # ADR 0086: "Target families" must not put a clearance target out of reach.
    cleared = first_category_skus(small_history)[0]
    targets = [{"sku_id": cleared, "sell_through": 0.5}]
    narrowing = {"mechanisms": ["BOGO"], "target_segments": ["Families"]}

    result = await tools.call(
        "generate_candidates",
        arguments(small_history, request={"clearance_targets": targets}, **narrowing),
    )
    whole = await tools.call(
        "generate_candidates", arguments(small_history, request={"clearance_targets": targets})
    )

    assert isinstance(result, ToolOk), result
    assert isinstance(whole, ToolOk), whole
    assert isinstance(result.output, GenerateCandidatesOutput)
    assert isinstance(whole.output, GenerateCandidatesOutput)
    assert result.output.not_narrowed == [cleared]
    assert whole.output.not_narrowed == []
    stored = store.get(result.output.candidate_set_id)
    unnarrowed = store.get(whole.output.candidate_set_id)
    assert stored is not None
    assert unnarrowed is not None
    spared = [line for line in stored.options.lines if line.sku_id == cleared]
    assert spared == [line for line in unnarrowed.options.lines if line.sku_id == cleared]
    assert {line.target_segment for line in spared} > {TargetSegment.FAMILIES}
    others = {
        (line.mechanism, line.target_segment)
        for line in stored.options.lines
        if line.sku_id != cleared
    }
    assert others <= {(Mechanism.BOGO, TargetSegment.FAMILIES)}
    assert "never narrow a SKU the request names for clearance" in " ".join(
        tools.specs()[0].description.split()
    )


async def test_the_same_call_on_models_fitted_alike_gets_the_same_candidate_set_id(
    small_models: tuple[DemandModel, Relations],
    small_dataset: GeneratedDataset,
    store: CandidateStore,
    small_history: DemandHistory,
) -> None:
    # A replayed tool round passes the recorded id back, so the id cannot be random (ADR 0049),
    # nor depend on how often the registry was retrained: CI and a fresh clone train version 1
    # of the models the cassettes were recorded on at another version (ADR 0054).
    tools = build(small_models, small_dataset, store)
    again = build(small_models, small_dataset, CandidateStore())
    retrained = build(small_models, small_dataset, CandidateStore(), demand_version=1)
    fitted_earlier = build(
        small_models, small_dataset, CandidateStore(), demand_as_of_week=SMALL_AS_OF - 1
    )

    async def set_id(registry: ToolRegistry, **changes: Any) -> object:
        result = await registry.call("generate_candidates", arguments(small_history, **changes))
        assert isinstance(result, ToolOk), result
        assert isinstance(result.output, GenerateCandidatesOutput)
        return result.output.candidate_set_id

    first = await set_id(tools)
    assert await set_id(again) == first
    assert await set_id(tools, mechanisms=["PCT_OFF"]) != first
    assert await set_id(tools, request={"marketing_budget": 100_000.0}) != first
    assert await set_id(retrained) == first
    assert await set_id(fitted_earlier) != first
    assert store.get(first) is not None  # type: ignore[arg-type]


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


# The planner's lever for a SKU the Critic flags: leave it out (ADR 0059).


def first_category_skus(small_history: DemandHistory) -> list[str]:
    products = small_history.products
    category = sorted(products["category"].unique())[0]
    return sorted(
        str(sku_id) for sku_id in products.loc[products["category"] == category, "sku_id"]
    )


async def test_the_planner_can_leave_skus_out(
    tools: ToolRegistry, store: CandidateStore, small_history: DemandHistory
) -> None:
    left_out = first_category_skus(small_history)[:2]

    result = await tools.call(
        "generate_candidates", arguments(small_history, exclude_sku_ids=left_out)
    )

    assert isinstance(result, ToolOk), result
    assert isinstance(result.output, GenerateCandidatesOutput)
    stored = store.get(result.output.candidate_set_id)
    assert stored is not None
    generated = {line.sku_id for line in stored.options.lines}
    assert generated, "the other SKUs still have options"
    assert not generated & set(left_out)
    assert all(match.sku_id not in left_out for match in stored.options.price_matches)


async def test_leaving_skus_out_combines_with_keeping_only_some(
    tools: ToolRegistry, store: CandidateStore, small_history: DemandHistory
) -> None:
    kept, left_out = first_category_skus(small_history)[:3], first_category_skus(small_history)[2]

    result = await tools.call(
        "generate_candidates",
        arguments(small_history, sku_ids=kept[:2], exclude_sku_ids=[left_out]),
    )

    assert isinstance(result, ToolOk), result
    assert isinstance(result.output, GenerateCandidatesOutput)
    stored = store.get(result.output.candidate_set_id)
    assert stored is not None
    assert {line.sku_id for line in stored.options.lines} <= set(kept[:2])


async def test_a_sku_left_out_changes_the_candidate_set_id(
    tools: ToolRegistry, small_history: DemandHistory
) -> None:
    async def set_id(**changes: Any) -> object:
        result = await tools.call("generate_candidates", arguments(small_history, **changes))
        assert isinstance(result, ToolOk), result
        assert isinstance(result.output, GenerateCandidatesOutput)
        return result.output.candidate_set_id

    left_out = first_category_skus(small_history)[:1]
    assert await set_id(exclude_sku_ids=left_out) != await set_id()


def exclusion_errors(small_history: DemandHistory) -> list[tuple[dict[str, Any], str]]:
    products = small_history.products
    skus = first_category_skus(small_history)
    category = sorted(products["category"].unique())[0]
    outside = str(products.loc[products["category"] != category, "sku_id"].iloc[0])
    target = [{"sku_id": skus[0], "sell_through": 0.5}]
    return [
        ({"exclude_sku_ids": [outside]}, f"not in the planning request's scope: {outside}"),
        ({"sku_ids": skus[:2], "exclude_sku_ids": skus[1:2]}, f"both kept and left out: {skus[1]}"),
        ({"exclude_sku_ids": skus}, "leaves no SKU"),
        (
            {"request": {"clearance_targets": target}, "exclude_sku_ids": skus[:1]},
            f"clearance target of the brief: {skus[0]}",
        ),
    ]


@pytest.mark.parametrize("case", range(4), ids=["outside", "both", "all", "clearance"])
async def test_a_sku_that_cannot_be_left_out_is_invalid_input(
    tools: ToolRegistry, small_history: DemandHistory, case: int
) -> None:
    changes, message = exclusion_errors(small_history)[case]

    result = await tools.call("generate_candidates", arguments(small_history, **changes))

    assert isinstance(result, ToolError)
    assert result.code == "invalid_input"
    assert message in result.message


async def test_a_narrowing_of_a_stored_set_is_read_off_it_and_prices_pairs_once(
    small_models: tuple[DemandModel, Relations],
    small_dataset: GeneratedDataset,
    tools: ToolRegistry,
    store: CandidateStore,
    small_history: DemandHistory,
) -> None:
    # The Critic's loop-back leaves SKUs out of the set the planner generated first (ADR 0077).
    left_out = first_category_skus(small_history)[:2]
    whole = await tools.call("generate_candidates", arguments(small_history))
    narrowed = await tools.call(
        "generate_candidates", arguments(small_history, exclude_sku_ids=left_out)
    )

    assert isinstance(whole, ToolOk)
    assert isinstance(narrowed, ToolOk)
    assert isinstance(whole.output, GenerateCandidatesOutput)
    assert isinstance(narrowed.output, GenerateCandidatesOutput)
    first = store.get(whole.output.candidate_set_id)
    second = store.get(narrowed.output.candidate_set_id)
    assert first is not None
    assert second is not None
    assert second.facts is first.facts  # pairwise terms already priced are not priced again
    kept = {id(line) for line in first.options.lines}
    assert all(id(line) in kept for line in second.options.lines)
    # What the planner sees is what generating the narrowed set afresh gives it.
    fresh = await build(small_models, small_dataset, CandidateStore()).call(
        "generate_candidates", arguments(small_history, exclude_sku_ids=left_out)
    )
    assert isinstance(fresh, ToolOk)
    assert isinstance(fresh.output, GenerateCandidatesOutput)
    registered = {"demand_model", "relations_model"}  # each build registers its own ids
    assert narrowed.output.model_dump(exclude=registered) == fresh.output.model_dump(
        exclude=registered
    )


# The planner's lever to promote a flagged SKU more gently instead (ADR 0084).


async def test_the_planner_can_cap_a_skus_depth_and_mechanisms(
    tools: ToolRegistry, store: CandidateStore, small_history: DemandHistory
) -> None:
    capped, only_pct = first_category_skus(small_history)[:2]
    limits = [
        {"sku_id": capped, "max_depth_pct": 15},
        {"sku_id": only_pct, "mechanisms": ["PCT_OFF"]},
    ]

    result = await tools.call("generate_candidates", arguments(small_history, sku_limits=limits))

    assert isinstance(result, ToolOk), result
    assert isinstance(result.output, GenerateCandidatesOutput)
    stored = store.get(result.output.candidate_set_id)
    assert stored is not None
    lines = stored.options.lines
    assert {line.depth_pct for line in lines if line.sku_id == capped} <= set(range(1, 16))
    assert {line.mechanism for line in lines if line.sku_id == only_pct} == {Mechanism.PCT_OFF}
    assert any(line.sku_id == capped for line in lines), "a capped SKU stays in the set"


async def test_a_sku_limit_changes_the_candidate_set_id(
    tools: ToolRegistry, small_history: DemandHistory
) -> None:
    async def set_id(**changes: Any) -> object:
        result = await tools.call("generate_candidates", arguments(small_history, **changes))
        assert isinstance(result, ToolOk), result
        assert isinstance(result.output, GenerateCandidatesOutput)
        return result.output.candidate_set_id

    capped = [{"sku_id": first_category_skus(small_history)[0], "max_depth_pct": 20}]
    assert await set_id(sku_limits=capped) != await set_id()


def limit_errors(small_history: DemandHistory) -> list[tuple[dict[str, Any], str]]:
    skus = first_category_skus(small_history)
    target = [{"sku_id": skus[0], "sell_through": 0.5}]
    return [
        (
            {"sku_limits": [{"sku_id": skus[0], "max_depth_pct": 60}]},
            f"loosens company policy: {skus[0]}'s max_depth_pct 60",
        ),
        (
            {
                "mechanisms": ["PCT_OFF"],
                "sku_limits": [{"sku_id": skus[0], "mechanisms": ["BOGO"]}],
            },
            f"loosens the call: {skus[0]}'s mechanisms name BOGO",
        ),
        (
            {
                "request": {"clearance_targets": target},
                "sku_limits": [{"sku_id": skus[0], "max_depth_pct": 10}],
            },
            f"may not limit a clearance target of the brief: {skus[0]}",
        ),
        (
            {"sku_limits": [{"sku_id": skus[0], "max_depth_pct": 2}]},
            f"leaves {skus[0]} no option",
        ),
    ]


@pytest.mark.parametrize("case", range(4), ids=["policy", "call", "clearance", "no-option"])
async def test_a_sku_limit_that_loosens_or_cannot_hold_is_invalid_input(
    tools: ToolRegistry, small_history: DemandHistory, case: int
) -> None:
    changes, message = limit_errors(small_history)[case]

    result = await tools.call("generate_candidates", arguments(small_history, **changes))

    assert isinstance(result, ToolError)
    assert result.code == "invalid_input"
    assert message in result.message


async def test_a_capped_narrowing_of_a_stored_set_is_read_off_it(
    small_models: tuple[DemandModel, Relations],
    small_dataset: GeneratedDataset,
    tools: ToolRegistry,
    store: CandidateStore,
    small_history: DemandHistory,
) -> None:
    capped = [{"sku_id": first_category_skus(small_history)[0], "max_depth_pct": 20}]
    whole = await tools.call("generate_candidates", arguments(small_history))
    narrowed = await tools.call("generate_candidates", arguments(small_history, sku_limits=capped))

    assert isinstance(whole, ToolOk)
    assert isinstance(narrowed, ToolOk)
    assert isinstance(whole.output, GenerateCandidatesOutput)
    assert isinstance(narrowed.output, GenerateCandidatesOutput)
    first = store.get(whole.output.candidate_set_id)
    second = store.get(narrowed.output.candidate_set_id)
    assert first is not None
    assert second is not None
    assert second.facts is first.facts
    fresh = await build(small_models, small_dataset, CandidateStore()).call(
        "generate_candidates", arguments(small_history, sku_limits=capped)
    )
    assert isinstance(fresh, ToolOk)
    assert isinstance(fresh.output, GenerateCandidatesOutput)
    registered = {"demand_model", "relations_model"}
    assert narrowed.output.model_dump(exclude=registered) == fresh.output.model_dump(
        exclude=registered
    )
