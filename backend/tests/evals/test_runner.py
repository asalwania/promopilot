"""`evals.run` plays tiny scenarios on the small generated world through the full agent graph,
with scripted LLMs, and scores each final plan (E9 seam 1, ADR 0056)."""

from collections.abc import Sequence
from typing import Any

import pytest
from pydantic import BaseModel

from promopilot.agents import BriefReading, PlanningSettings
from promopilot.config import Settings
from promopilot.datagen import GeneratedDataset
from promopilot.domain import CompanyPolicy, Mechanism, Region, SolveStatus
from promopilot.evals import EvalWorld, FittedModels, Scenario, run
from promopilot.evals.report import ConstraintCheck, EvalReport, RunOutcome, RunResult
from promopilot.llm import FakeProvider, LLMError, LLMProvider, Message, ToolSpec, ToolTurn
from promopilot.models.demand import DemandModel
from promopilot.models.relations import Relations
from tests.conftest import SMALL_AS_OF
from tests.unit.agents.fakes import DownProvider

FREE = CompanyPolicy(margin_floor=0.10, fixed_cost_per_line_week=dict.fromkeys(Mechanism, 0.0))
"""Without fixed marketing costs, some of the small world's options pay for themselves."""

PLAIN = Scenario(
    name="plain",
    group="standard_festive",
    brief="Plan a Diwali promotion for Snacks in North with a marketing budget of ₹20k.",
    as_of_week=SMALL_AS_OF,
    seed=1,
    expect=({"declares_infeasible": False},),
)
CLARIFY = Scenario(
    name="clarify",
    group="vague_or_conflicting",
    brief="Plan a Diwali promotion for Snacks in North.",
    as_of_week=SMALL_AS_OF,
    seed=1,
    clarifications={"marketing_budget": "₹20k"},
    expect=({"asks_clarification": "marketing_budget"},),
)
AMEND = Scenario(
    name="amend",
    group="mid_plan_amendments",
    brief="Plan a Diwali promotion for Snacks in North and South with a marketing budget of ₹20k.",
    as_of_week=SMALL_AS_OF,
    seed=1,
    amendments=("Drop South",),
    expect=({"excludes_region": "South"},),
)


@pytest.fixture
def world(
    small_dataset: GeneratedDataset, small_models: tuple[DemandModel, Relations]
) -> EvalWorld:
    return EvalWorld(small_dataset, fitted={SMALL_AS_OF: FittedModels(*small_models)})


async def evaluate(
    world: EvalWorld,
    scenarios: Sequence[Scenario],
    provider: LLMProvider | None = None,
    runs: int = 1,
) -> EvalReport:
    return await run(
        scenarios,
        provider or DownProvider(),
        runs,
        world=world,
        # Fewer simulated runs than the default keep these sessions quick.
        settings=PlanningSettings.from_settings(Settings(simulation_runs=200)),
        policy=FREE,
    )


def only_run(report: EvalReport, name: str) -> RunResult:
    [scenario] = [scenario for scenario in report.scenarios if scenario.name == name]
    [played] = scenario.runs
    return played


async def test_every_final_plan_is_checked_and_scored_with_answers_and_amendments_applied(
    world: EvalWorld,
) -> None:
    report = await evaluate(world, [PLAIN, CLARIFY, AMEND])

    satisfaction, breaches = report.metrics
    assert (satisfaction.name, satisfaction.count, satisfaction.of) == (
        "constraint_satisfaction",
        3,
        3,
    )
    assert (satisfaction.target, satisfaction.passed) == (1.0, True)
    assert (breaches.name, breaches.of, breaches.target) == ("oracle_breach_rate", 3, None)
    assert [scenario.name for scenario in report.scenarios] == ["plain", "clarify", "amend"]
    assert all(scenario.passed for scenario in report.scenarios)

    plain = only_run(report, "plain")
    assert plain.outcome is RunOutcome.PLANNED
    assert plain.constraints is ConstraintCheck.PASSED
    assert plain.revision is not None
    assert plain.revision.lines > 0
    assert plain.revision.solver_status is SolveStatus.OPTIMAL
    assert plain.oracle is not None
    assert plain.oracle.promo_cost > 0
    assert "context: llm_unavailable" in plain.fallbacks

    clarify = only_run(report, "clarify")
    assert clarify.questions_asked == ("marketing_budget",)
    assert clarify.revision is not None
    assert clarify.revision.marketing_budget == 20_000.0
    assert [p.passed for p in clarify.properties] == [True]

    amend = only_run(report, "amend")
    assert amend.amendments_applied == 1
    assert amend.revision is not None
    assert amend.revision.number == 2
    assert amend.revision.regions == (Region.NORTH,)
    assert [p.passed for p in amend.properties] == [True]


async def test_a_failing_expected_property_fails_its_run_and_scenario(world: EvalWorld) -> None:
    wrong = Scenario.model_validate(
        {**PLAIN.model_dump(), "name": "wrong", "expect": [{"excludes_region": "North"}]}
    )

    report = await evaluate(world, [wrong])

    [scenario] = report.scenarios
    [played] = scenario.runs
    [result] = played.properties
    assert (result.property, result.passed) == ("excludes_region: North", False)
    assert "North" in result.detail
    assert not played.passed
    assert not scenario.passed
    assert played.constraints is ConstraintCheck.PASSED, "properties do not touch constraints"


async def test_the_run_is_deterministic_for_a_seed(world: EvalWorld) -> None:
    first = await evaluate(world, [AMEND], runs=2)
    second = await evaluate(world, [AMEND])

    one, two = first.scenarios[0].runs
    assert one.model_dump(exclude={"run", "duration_s"}) == two.model_dump(
        exclude={"run", "duration_s"}
    )
    assert (
        second.comparable()["scenarios"][0]["runs"][0]
        == first.comparable()["scenarios"][0]["runs"][0]
    )
    assert second.comparable()["metrics"][0]["value"] == first.comparable()["metrics"][0]["value"]


async def test_the_scripted_llm_reads_the_brief_and_what_it_cannot_answer_falls_back(
    world: EvalWorld,
) -> None:
    reading = BriefReading(
        regions=[Region.NORTH],
        categories=["Snacks"],
        sku_ids=None,
        promo_start_week=SMALL_AS_OF + 2,
        promo_end_week=SMALL_AS_OF + 3,
        marketing_budget=20_000.0,
        min_margin=None,
    )
    down = [LLMError("down after the reading") for _ in range(10)]

    report = await evaluate(world, [PLAIN], FakeProvider([reading, *down]))

    plain = only_run(report, "plain")
    assert plain.outcome is RunOutcome.PLANNED
    assert not any(fallback.startswith("context") for fallback in plain.fallbacks)
    assert "planner: llm_unavailable" in plain.fallbacks
    assert report.provider == "FakeProvider"


async def test_an_unanswered_question_ends_the_run_with_no_plan_to_score(world: EvalWorld) -> None:
    unanswered = Scenario.model_validate(
        {**CLARIFY.model_dump(), "clarifications": {}, "expect": [{"excludes_region": "South"}]}
    )

    report = await evaluate(world, [unanswered])

    played = only_run(report, "clarify")
    assert played.outcome is RunOutcome.AWAITING_CLARIFICATION
    assert played.questions_asked == ("marketing_budget",)
    assert (played.constraints, played.oracle, played.revision) == (
        ConstraintCheck.NO_PLAN,
        None,
        None,
    )
    assert [(p.passed, p.detail) for p in played.properties] == [(False, "no final plan revision")]
    assert report.metrics[0].value is None


class Broken:
    """A provider with a bug: not an LLM failure, so nothing falls back."""

    async def complete_structured[T: BaseModel](
        self, schema: type[T], messages: Sequence[Message]
    ) -> T:
        raise RuntimeError("provider bug")

    async def complete_with_tools(
        self, tools: Sequence[ToolSpec], messages: Sequence[Message]
    ) -> ToolTurn:
        raise RuntimeError("provider bug")


async def test_a_session_that_fails_is_reported_and_the_eval_goes_on(world: EvalWorld) -> None:
    report = await evaluate(world, [PLAIN], Broken())

    played = only_run(report, "plain")
    assert played.outcome is RunOutcome.FAILED
    assert played.error == "RuntimeError: provider bug"
    assert not report.scenarios[0].passed


@pytest.mark.parametrize("runs", [0, -1])
async def test_a_scenario_runs_at_least_once(world: EvalWorld, runs: Any) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        await evaluate(world, [PLAIN], runs=runs)
