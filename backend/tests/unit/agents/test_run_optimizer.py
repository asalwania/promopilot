"""`run_optimizer` through the tool registry: select the plan from a stored candidate set
(ADR 0036)."""

from collections.abc import Sequence
from typing import Any
from uuid import uuid4

import pandas as pd
import pytest

from promopilot.agents.tools import ToolError, ToolOk, ToolRegistry
from promopilot.agents.tools.as_of import fixed_as_of_week
from promopilot.agents.tools.generate_candidates import (
    GenerateCandidatesOutput,
    generate_candidates_tool,
)
from promopilot.agents.tools.run_optimizer import (
    RunOptimizerInput,
    RunOptimizerOutput,
    run_optimizer_tool,
)
from promopilot.datagen import GeneratedDataset
from promopilot.domain import (
    CompanyPolicy,
    ConstraintKind,
    ConstraintSource,
    Mechanism,
    NotSelectedReason,
    PlanLine,
    PlanningRequest,
    PromoWindow,
    Region,
    Scope,
    SelectionReason,
    SelectionReasonCode,
    TargetSegment,
    WhyChosen,
)
from promopilot.guardrails import LineFacts, PlanFacts, SkuFacts, validate_plan
from promopilot.models.demand import DemandHistory, DemandModel
from promopilot.models.registry import ModelKind
from promopilot.models.relations import Relations
from promopilot.optimizer import (
    TABLE_COLUMNS,
    CandidateStore,
    PromoOptions,
    PruneReason,
    SolverSettings,
    SolveStatus,
)
from tests.conftest import SMALL_AS_OF
from tests.unit.agents.fakes import InMemoryRetailData
from tests.unit.agents.test_generate_candidates import Fixed, arguments, entry

POLICY = CompanyPolicy(margin_floor=0.10)
REQUEST = PlanningRequest(
    as_of_week=10,
    scope=Scope(regions=(Region.NORTH,), categories=("Snacks",)),
    promo_window=PromoWindow(start_week=11, end_week=12),
    marketing_budget=1_500.0,
    min_margin=0.05,
)


def line(sku_id: str) -> PlanLine:
    return PlanLine(
        sku_id=sku_id,
        region=Region.NORTH,
        mechanism=Mechanism.PCT_OFF,
        depth_pct=10,
        duration_weeks=2,
        start_week=11,
        target_segment=TargetSegment.ALL_CUSTOMERS,
    )


class Facts:
    """A and B are substitutes that lose ₹150 together."""

    def sku(self, sku_id: str, region: Region) -> SkuFacts:
        return SkuFacts(category="Snacks", base_price=100.0, unit_cost=50.0, overstocked=False)

    def pairwise_cannibalisation(
        self, pairs: Sequence[tuple[PlanLine, PlanLine]]
    ) -> Sequence[float]:
        return [150.0 if {a.sku_id, b.sku_id} == {"A", "B"} else 0.0 for a, b in pairs]


def hand_built() -> PromoOptions:
    table = pd.DataFrame(0.0, index=range(3), columns=TABLE_COLUMNS)
    table["value"] = [500.0, 400.0, -20.0]
    table["incremental_profit"] = [450.0, 400.0, -20.0]
    table["cannibalised_profit"] = [10.0, 0.0, 0.0]
    table["halo_profit"] = [60.0, 0.0, 0.0]
    table["promo_cost"] = [700.0, 600.0, 100.0]
    table["revenue"] = [5_000.0, 4_000.0, 1_000.0]
    table["gross_profit"] = [1_000.0, 800.0, 100.0]
    table["units"] = [60.0, 50.0, 10.0]
    table["p90_units"] = [70.0, 60.0, 12.0]
    table["available_stock"] = [500.0, 500.0, 500.0]
    return PromoOptions(
        lines=(line("A"), line("B"), line("C")),
        table=table,
        enumerated=3,
        pruned=dict.fromkeys(PruneReason, 0),
    )


@pytest.fixture
def store() -> CandidateStore:
    return CandidateStore()


def registry(store: CandidateStore) -> ToolRegistry:
    return ToolRegistry(
        [run_optimizer_tool(store, policy=POLICY, settings=SolverSettings(), seed=0)]
    )


def test_the_registry_lists_run_optimizer_with_its_schemas(store: CandidateStore) -> None:
    [spec] = registry(store).specs()

    assert spec.name == "run_optimizer"
    assert spec.input_schema == RunOptimizerInput.model_json_schema()
    assert spec.output_schema == RunOptimizerOutput.model_json_schema(mode="serialization")


async def test_a_call_returns_the_selected_plan_with_its_numbers(store: CandidateStore) -> None:
    stored = store.put(REQUEST, hand_built(), Facts())

    result = await registry(store).call(
        "run_optimizer", {"candidate_set_id": str(stored.candidate_set_id)}
    )

    assert isinstance(result, ToolOk), result
    output = result.output
    assert isinstance(output, RunOptimizerOutput)
    RunOptimizerOutput.model_validate(output.model_dump(mode="json"))
    assert output.candidate_set_id == stored.candidate_set_id
    assert output.status is SolveStatus.OPTIMAL
    # A and B together: 900 - 150 = 750 beats A alone (500), and costs 1,300 of 1,500.
    assert [row.option for row in output.lines] == [line("A"), line("B")]
    assert output.objective == pytest.approx(750.0)
    assert output.pairwise_cannibalisation == pytest.approx(150.0)
    first = output.lines[0]
    assert (first.units, first.p90_units, first.available_stock) == (60.0, 70.0, 500.0)
    assert (first.promo_cost, first.incremental_profit, first.value) == (700.0, 450.0, 500.0)
    assert (first.cannibalised_profit, first.halo_profit, first.clearance_value) == (10.0, 60, 0)
    assert (first.revenue, first.gross_profit) == (5_000.0, 1_000.0)
    assert output.total_promo_cost == pytest.approx(1_300.0)
    assert output.marketing_budget == 1_500.0
    assert output.blended_margin == pytest.approx(1_800 / 9_000)
    assert output.min_margin == pytest.approx(0.10)  # the request's 5% is held at the floor
    assert (output.candidate_options, output.eligible_options, output.pairs) == (3, 2, 1)
    assert output.binding_constraints == []
    assert first.why_chosen == WhyChosen(
        reasons=(
            SelectionReason(code=SelectionReasonCode.INCREMENTAL_PROFIT, amount=450.0),
            SelectionReason(code=SelectionReasonCode.HALO, amount=60.0),
        ),
        value=500.0,
        best_for_sku_region=True,
    )
    assert [(entry.option, entry.reasons) for entry in output.not_selected] == [
        (line("C"), (NotSelectedReason.LOW_UPLIFT,))
    ]


async def test_a_binding_budget_is_reported_in_domain_terms(store: CandidateStore) -> None:
    tight = REQUEST.model_copy(update={"marketing_budget": 1_000.0})
    stored = store.put(tight, hand_built(), Facts())

    result = await registry(store).call(
        "run_optimizer", {"candidate_set_id": str(stored.candidate_set_id)}
    )

    assert isinstance(result, ToolOk), result
    assert isinstance(result.output, RunOptimizerOutput)
    [binding] = result.output.binding_constraints
    assert (binding.kind, binding.source, binding.limit) == (
        ConstraintKind.MARKETING_BUDGET,
        ConstraintSource.BRIEF,
        1_000.0,
    )


async def test_an_unknown_or_evicted_candidate_set_must_be_regenerated(
    store: CandidateStore,
) -> None:
    result = await registry(store).call("run_optimizer", {"candidate_set_id": str(uuid4())})

    assert isinstance(result, ToolError)
    assert result.code == "invalid_input"
    assert "generate_candidates" in result.message


async def test_schema_violations_are_invalid_input(store: CandidateStore) -> None:
    result = await registry(store).call("run_optimizer", {"candidate_set_id": "nope"})

    assert isinstance(result, ToolError)
    assert result.code == "invalid_input"


async def test_the_fitted_models_candidates_are_optimised_the_same_way_twice(
    small_models: tuple[DemandModel, Relations],
    small_dataset: GeneratedDataset,
    small_history: DemandHistory,
    store: CandidateStore,
) -> None:
    model, found = small_models
    # At the default policy some of the small world's options pay for themselves (ADR 0037).
    policy = CompanyPolicy()
    tools = ToolRegistry(
        [
            generate_candidates_tool(
                Fixed((entry(ModelKind.DEMAND, 1), model)),
                Fixed((entry(ModelKind.RELATIONS, 1), found)),
                InMemoryRetailData(small_dataset),
                fixed_as_of_week(SMALL_AS_OF),
                policy=policy,
                store=store,
            ),
            run_optimizer_tool(store, policy=policy, settings=SolverSettings(), seed=0),
        ]
    )
    generated = await tools.call(
        "generate_candidates", arguments(small_history, request=_all_categories(small_history))
    )
    assert isinstance(generated, ToolOk), generated
    assert isinstance(generated.output, GenerateCandidatesOutput)
    call = {"candidate_set_id": str(generated.output.candidate_set_id)}

    first = await tools.call("run_optimizer", call)
    again = await tools.call("run_optimizer", call)

    assert isinstance(first, ToolOk), first
    assert isinstance(again, ToolOk)
    assert first.output == again.output
    output = first.output
    assert isinstance(output, RunOptimizerOutput)
    assert output.status is SolveStatus.OPTIMAL
    assert output.total_promo_cost <= output.marketing_budget
    assert output.lines
    assert all(row.value > 0 for row in output.lines)
    stored = store.get(output.candidate_set_id)
    assert stored is not None
    plan = PlanFacts(
        lines=tuple(
            LineFacts(
                line=row.option,
                anchor=stored.facts.sku(row.option.sku_id, row.option.region),
                partner=(
                    None
                    if row.option.bundle_partner_sku_id is None
                    else stored.facts.sku(row.option.bundle_partner_sku_id, row.option.region)
                ),
                expected_units=row.units,
                p90_units=row.p90_units,
                available_stock=row.available_stock,
                expected_revenue=row.revenue,
                expected_gross_profit=row.gross_profit,
                promo_cost=row.promo_cost,
            )
            for row in output.lines
        )
    )
    assert validate_plan(plan, stored.request, policy) == ()


def _all_categories(history: DemandHistory) -> dict[str, Any]:
    categories = sorted(history.products["category"].unique())
    return {
        "scope": {"regions": ["North", "South"], "categories": categories},
        "marketing_budget": 50_000.0,
    }
