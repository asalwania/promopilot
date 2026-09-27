"""`relax_constraints` through the tool registry: the smallest relaxation of an infeasible
request's brief constraints (ADR 0044)."""

from dataclasses import replace
from uuid import uuid4

import pytest

from promopilot.agents.tools import ToolError, ToolOk, ToolRegistry
from promopilot.agents.tools.relax_constraints import (
    RelaxConstraintsInput,
    RelaxConstraintsOutput,
    relax_constraints_tool,
)
from promopilot.agents.tools.run_optimizer import RunOptimizerOutput, run_optimizer_tool
from promopilot.domain import (
    BindingEvidence,
    ClearanceTarget,
    ConstraintKind,
    Region,
    SolveStatus,
)
from promopilot.optimizer import (
    CandidateStore,
    ClearanceBaseline,
    PromoOptions,
    SolverSettings,
    relaxed_request,
)
from tests.unit.agents.test_run_optimizer import POLICY, REQUEST, Facts, hand_built

NAMED = REQUEST.model_copy(
    update={"clearance_targets": (ClearanceTarget(sku_id="C", sell_through=0.5),)}
)
"""C sells 100 of its 1,000 units unpromoted; its only option adds 50: 50% is out of reach."""


def clearing_c() -> PromoOptions:
    options = hand_built()
    options.table.loc[2, "window_uplift"] = 50.0
    return replace(
        options,
        clearance=(
            ClearanceBaseline(
                sku_id="C", region=Region.NORTH, available_stock=1_000.0, baseline_units=100.0
            ),
        ),
    )


@pytest.fixture
def store() -> CandidateStore:
    return CandidateStore()


def registry(store: CandidateStore) -> ToolRegistry:
    settings = SolverSettings()
    return ToolRegistry(
        [
            relax_constraints_tool(store, policy=POLICY, settings=settings, seed=0),
            run_optimizer_tool(store, policy=POLICY, settings=settings, seed=0),
        ]
    )


def test_the_registry_lists_relax_constraints_with_its_schemas(store: CandidateStore) -> None:
    spec = next(spec for spec in registry(store).specs() if spec.name == "relax_constraints")

    assert spec.input_schema == RelaxConstraintsInput.model_json_schema()
    assert spec.output_schema == RelaxConstraintsOutput.model_json_schema(mode="serialization")


async def test_an_infeasible_request_gets_its_smallest_relaxation(store: CandidateStore) -> None:
    stored = store.put(NAMED, clearing_c(), Facts())

    result = await registry(store).call(
        "relax_constraints", {"candidate_set_id": str(stored.candidate_set_id)}
    )

    assert isinstance(result, ToolOk), result
    output = result.output
    assert isinstance(output, RelaxConstraintsOutput)
    # The output round-trips through its own JSON schema's model.
    assert RelaxConstraintsOutput.model_validate_json(output.model_dump_json()) == output
    assert output.status is SolveStatus.INFEASIBLE
    assert output.relaxation is not None
    assert output.relaxation.policy_binds
    (change,) = output.relaxation.changes
    assert (change.kind, change.sku_id, change.current) == (
        ConstraintKind.CLEARANCE_TARGET,
        "C",
        0.5,
    )
    assert change.relaxed == pytest.approx(0.15)
    assert [(c.kind, c.evidence) for c in output.binding_constraints] == [
        (ConstraintKind.CLEARANCE_TARGET, BindingEvidence.INFEASIBLE)
    ]
    assert [s.sku_id for s in output.clearance_shortfalls] == ["C"]
    relaxed = relaxed_request(NAMED, output.relaxation)
    assert relaxed.clearance_targets == (ClearanceTarget(sku_id="C", sell_through=0.15),)


async def test_a_feasible_request_has_nothing_to_relax(store: CandidateStore) -> None:
    stored = store.put(REQUEST, hand_built(), Facts())

    result = await registry(store).call(
        "relax_constraints", {"candidate_set_id": str(stored.candidate_set_id)}
    )

    assert isinstance(result, ToolOk), result
    output = result.output
    assert isinstance(output, RelaxConstraintsOutput)
    assert output.status is SolveStatus.OPTIMAL
    assert output.relaxation is None
    assert output.binding_constraints == []


async def test_run_optimizer_reports_the_relaxation_too(store: CandidateStore) -> None:
    stored = store.put(NAMED, clearing_c(), Facts())

    result = await registry(store).call(
        "run_optimizer", {"candidate_set_id": str(stored.candidate_set_id)}
    )

    assert isinstance(result, ToolOk), result
    output = result.output
    assert isinstance(output, RunOptimizerOutput)
    assert output.status is SolveStatus.INFEASIBLE
    assert output.relaxation is not None


async def test_an_unknown_candidate_set_must_be_regenerated(store: CandidateStore) -> None:
    result = await registry(store).call("relax_constraints", {"candidate_set_id": str(uuid4())})

    assert isinstance(result, ToolError)
    assert result.code == "invalid_input"
    assert "generate_candidates" in result.message


async def test_schema_violations_are_invalid_input(store: CandidateStore) -> None:
    result = await registry(store).call(
        "relax_constraints", {"candidate_set_id": "nope", "budget": 1}
    )

    assert isinstance(result, ToolError)
    assert result.code == "invalid_input"
