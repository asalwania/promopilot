"""`evals.run` plays tiny scenarios on the small generated world through the full agent graph,
with scripted LLMs, and scores each final plan (E9 seam 1, ADR 0056)."""

import asyncio
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from promopilot.agents import BriefReading, ClearanceAsk, LLMPricing, PlanningSettings
from promopilot.config import ModelPrice, Settings
from promopilot.datagen import GeneratedDataset
from promopilot.domain import (
    CompanyPolicy,
    ExplanationSource,
    FallbackReason,
    Mechanism,
    Region,
    SolveStatus,
)
from promopilot.evals import EvalWorld, FittedModels, Scenario, run, runner
from promopilot.evals.report import (
    ConstraintCheck,
    EvalReport,
    ExplainerRun,
    Metric,
    RunOutcome,
    RunResult,
)
from promopilot.llm import (
    FakeProvider,
    LLMError,
    LLMProvider,
    Message,
    ReplayProvider,
    ToolSpec,
    ToolTurn,
    Usage,
)
from promopilot.models.demand import DemandModel
from promopilot.models.relations import Relations
from tests.conftest import SMALL_AS_OF
from tests.unit.agents.billed import BilledProvider
from tests.unit.agents.fakes import DownProvider

FREE = CompanyPolicy(margin_floor=0.10, fixed_cost_per_line_week=dict.fromkeys(Mechanism, 0.0))
"""Without fixed marketing costs, some of the small world's options pay for themselves."""

PLAIN = Scenario(
    name="plain",
    group="standard_festive",
    brief="Plan a Diwali promotion for Snacks in North with a marketing budget of ₹20k.",
    as_of_week=SMALL_AS_OF,
    seed=1,
    labels={"regions": ["North"], "categories": ["Snacks"], "marketing_budget": 20_000},
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
    expect=({"excludes_region": "South"}, {"diff_changes": "scope.regions"}),
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
    pricing: LLMPricing | None = None,
) -> EvalReport:
    return await run(
        scenarios,
        provider or DownProvider(),
        runs,
        world=world,
        # Fewer simulated runs than the default keep these sessions quick.
        settings=PlanningSettings.from_settings(Settings(simulation_runs=200)),
        policy=FREE,
        pricing=pricing,
    )


def metric(report: EvalReport, name: str) -> Metric:
    """A metric by name: other tickets add metrics, so none is looked up by position."""
    [found] = [metric for metric in report.metrics if metric.name == name]
    return found


def only_run(report: EvalReport, name: str) -> RunResult:
    [scenario] = [scenario for scenario in report.scenarios if scenario.name == name]
    [played] = scenario.runs
    return played


async def test_every_final_plan_is_checked_and_scored_with_answers_and_amendments_applied(
    world: EvalWorld,
) -> None:
    report = await evaluate(world, [PLAIN, CLARIFY, AMEND])

    satisfaction = metric(report, "constraint_satisfaction")
    breaches = metric(report, "oracle_breach_rate")
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
    assert [p.passed for p in amend.properties] == [True, True]


async def test_every_scored_plan_is_compared_with_the_rule_based_baseline_and_the_best_plan(
    world: EvalWorld,
) -> None:
    report = await evaluate(world, [PLAIN, AMEND])

    quality, regret = metric(report, "plan_quality"), metric(report, "regret")
    assert (quality.of, quality.target, quality.direction) == (2, 0.9, "at_least")
    assert (regret.of, regret.target, regret.direction) == (2, 0.10, "at_most")
    assert quality.passed is not None
    assert regret.passed is not None
    consistency = metric(report, "consistency")
    assert (consistency.value, consistency.passed) == (None, None), "one run per scenario"

    plain = only_run(report, "plain")
    assert plain.oracle is not None
    assert plain.quality is not None
    assert plain.revision is not None
    assert plain.quality.objective == pytest.approx(
        plain.oracle.incremental_profit + plain.oracle.clearance_value
    )
    assert plain.quality.best.objective is not None
    assert plain.quality.regret is not None
    assert plain.revision.sku_ids
    # The default sequence's plan for the same request splits the regret by cause (ADR 0078).
    assert plain.quality.default is not None
    parts = plain.quality.breakdown
    assert parts is not None
    assert parts.model_error + parts.planner + parts.timeouts == pytest.approx(plain.quality.regret)
    assert regret.breakdown.keys() == {
        "best_infeasible",
        "best_timed_out",
        "largest_model_error",
        "largest_planner",
        "largest_timeouts",
    }
    # Both plans are built on the final request: after "Drop South", North only.
    amend = only_run(report, "amend")
    assert amend.quality is not None
    assert amend.quality.rule_based.lines == len(amend.quality.rule_based.sku_ids)


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
    timing = {"run", "duration_s", "session_s", "llm_s"}
    assert one.model_dump(exclude=timing) == two.model_dump(exclude=timing)
    assert (
        second.comparable()["scenarios"][0]["runs"][0]
        == first.comparable()["scenarios"][0]["runs"][0]
    )
    for name in ("constraint_satisfaction", "plan_quality", "regret"):
        assert metric(second, name).value == metric(first, name).value
    # Two identical runs promote the same SKUs.
    assert first.scenarios[0].consistency == 1.0
    assert metric(first, "consistency").value == 1.0
    assert metric(second, "consistency").value is None


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


async def test_every_request_no_cassette_holds_is_listed_on_its_run(
    world: EvalWorld, tmp_path: Path
) -> None:
    replayed = await evaluate(world, [PLAIN], ReplayProvider(tmp_path))
    down = await evaluate(world, [PLAIN])

    missed = only_run(replayed, "plain").cassette_misses
    assert missed, "an empty cassette folder misses every request"
    assert all(len(digest) == 64 for digest in missed)
    assert len(set(missed)) == len(missed), "each request is listed once"
    assert "context: cassette_missing" in only_run(replayed, "plain").fallbacks
    assert only_run(down, "plain").cassette_misses == (), "a failing LLM is not a miss"


async def test_an_unanswered_question_ends_the_run_with_no_plan_to_score(world: EvalWorld) -> None:
    unanswered = Scenario.model_validate(
        {
            **CLARIFY.model_dump(),
            "clarifications": {},
            "expect": [{"asks_clarification": "marketing_budget"}, {"excludes_region": "South"}],
        }
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
    assert [(p.passed, p.detail) for p in played.properties] == [
        (True, "asked about marketing_budget"),
        (False, "no final plan revision"),
    ]
    assert metric(report, "constraint_satisfaction").value is None
    assert metric(report, "plan_quality").value is None


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


async def test_the_agents_behaviour_is_scored_from_each_session(world: EvalWorld) -> None:
    report = await evaluate(world, [PLAIN, CLARIFY, AMEND])

    metrics = {metric.name: metric for metric in report.metrics}
    assert {
        "extraction_accuracy",
        "clarification_behaviour",
        "infeasibility_handling",
        "grounding",
        "session_latency_p50",
        "session_cost_p50",
    } <= set(metrics)
    extraction = metrics["extraction_accuracy"]
    assert (extraction.count, extraction.of, extraction.passed) == (3, 3, True)
    clarification = metrics["clarification_behaviour"]
    assert (clarification.count, clarification.of, clarification.passed) == (1, 1, True)
    assert metrics["infeasibility_handling"].of == 0
    # The LLM is down: every Explainer run fell back with nothing to check.
    assert (metrics["grounding"].of, metrics["grounding"].breakdown["llm_unavailable"]) == (0, 4)
    latency = metrics["session_latency_p50"]
    assert (latency.unit, latency.count, latency.target) == ("seconds", 3, None)
    assert latency.value is not None
    assert latency.value > 0
    assert (metrics["session_cost_p50"].value, metrics["session_cost_p50"].unit) == (0.0, "rupees")

    plain = only_run(report, "plain")
    assert [(m.field, m.matched) for m in plain.extraction] == [
        ("regions", True),
        ("categories", True),
        ("marketing_budget", True),
    ]
    assert (plain.clarification, plain.infeasibility, plain.unneeded_asks) == (None, None, ())
    assert 0 < plain.session_s <= plain.duration_s
    clarify = only_run(report, "clarify")
    assert clarify.clarification is not None
    assert clarify.clarification.asked == ("marketing_budget",)
    amend = only_run(report, "amend")
    down = FallbackReason.LLM_UNAVAILABLE
    assert amend.explanations == (
        ExplainerRun(revision=1, source=ExplanationSource.TEMPLATE, fallback_reason=down),
        ExplainerRun(revision=2, source=ExplanationSource.TEMPLATE, fallback_reason=down),
    )


async def test_a_sessions_cost_is_the_sum_of_its_priced_token_usage(world: EvalWorld) -> None:
    reading = BriefReading(
        regions=[Region.NORTH],
        categories=["Snacks"],
        sku_ids=None,
        promo_start_week=SMALL_AS_OF + 2,
        promo_end_week=SMALL_AS_OF + 3,
        marketing_budget=20_000.0,
        min_margin=None,
    )
    down = [LLMError("down after the reading") for _ in range(30)]
    billed = BilledProvider(
        FakeProvider([reading, *down]),
        [Usage(model="m", input_tokens=1_000, output_tokens=0) for _ in range(31)],
    )
    # 1,000 input tokens at $1 per million is $0.001, or ₹0.096 at ₹96 to the dollar.
    pricing = LLMPricing(
        prices={"m": ModelPrice(input_usd_per_mtok=1.0, output_usd_per_mtok=0.0)},
        usd_inr_rate=96.0,
    )

    report = await evaluate(world, [PLAIN], billed, pricing=pricing)

    usage = only_run(report, "plain").usage
    assert usage.calls >= 2, "the reading and at least the planner's failed call are billed"
    assert (usage.input_tokens, usage.output_tokens) == (1_000 * usage.calls, 0)
    assert usage.cost_usd == pytest.approx(0.001 * usage.calls)
    assert usage.cost_inr == pytest.approx(0.096 * usage.calls)
    cost = metric(report, "session_cost_p50")
    assert cost.value == pytest.approx(usage.cost_inr)
    assert cost.breakdown["calls"] == usage.calls


async def test_the_report_has_the_model_recovery_metrics_once(world: EvalWorld) -> None:
    report = await evaluate(world, [PLAIN])

    recovery = metric(report, "elasticity_recovery")
    assert (recovery.target, recovery.value is not None) == (0.2, True)
    for name in ("substitute_precision", "complement_recall", "baseline_wape_region_sku"):
        assert metric(report, name).of >= 0


async def test_strong_substitutes_are_checked_against_the_pairs_in_the_final_requests_scope(
    world: EvalWorld,
) -> None:
    cannibal = Scenario.model_validate(
        {
            **PLAIN.model_dump(),
            "name": "cannibal",
            "group": "heavy_cannibalisation",
            "expect": [{"no_strong_substitutes_together": True}],
        }
    )

    report = await evaluate(world, [cannibal])

    [result] = only_run(report, "cannibal").properties
    assert result.property == "no_strong_substitutes_together: true"
    # The small world's Snacks hold one strong pair (SKU0003, SKU0004): it was handed over.
    assert "no strong substitute pair in scope" not in result.detail
    assert "SKU0003 and SKU0004" in result.detail or "none of the 1 strong" in result.detail


# ---------------------------------------------------------------- accepting a relaxation

CLEAR = "Crunchy Biscuits 250g"
"""SKU0005, the small world's Snacks SKU with the most stock cover in North: all of it cannot
sell in two weeks, so the first plan is infeasible with a proven relaxation (ADR 0044)."""
OVERREACH = Scenario(
    name="overreach",
    group="mid_plan_amendments",
    brief=(
        f"Plan a promotion for Snacks in North for weeks {SMALL_AS_OF + 2}-{SMALL_AS_OF + 3} "
        f"with a marketing budget of ₹20k. Clear 100% of {CLEAR} stock."
    ),
    as_of_week=SMALL_AS_OF,
    seed=1,
    amendments=({"accept_relaxation": True},),
    labels={
        "marketing_budget": 20_000,
        "clearance_targets": [{"sku_id": "SKU0005", "sell_through": 1.0}],
    },
    expect=(
        {"declares_infeasible": False},
        {"meets_clearance": "SKU0005"},
        {"diff_changes": "clearance_targets"},
    ),
)
_ACCEPTED = re.compile(r"lower the clearance target for SKU0005 to ([\d.]+)% sell-through")


class ReadsTheAccept:
    """The Context agent's LLM reads only the amendment that accepts a relaxation, as the live
    model would; every other call fails, so the rules read the brief (they cannot read an
    accepted relaxation's text) and the planner and Explainer fall back."""

    def __init__(self) -> None:
        self.accepted: list[float] = []

    async def complete_structured[T: BaseModel](
        self, schema: type[T], messages: Sequence[Message]
    ) -> T:
        said = [found for m in messages for found in _ACCEPTED.findall(m.content)]
        if schema is not BriefReading or not said:
            raise LLMError("down but for the accepted relaxation")
        sell_through = float(said[-1]) / 100
        self.accepted.append(sell_through)
        reading = BriefReading(
            regions=[Region.NORTH],
            categories=["Snacks"],
            sku_ids=None,
            promo_start_week=SMALL_AS_OF + 2,
            promo_end_week=SMALL_AS_OF + 3,
            marketing_budget=20_000.0,
            min_margin=None,
            clearance=[ClearanceAsk(products=CLEAR, sell_through=sell_through)],
        )
        return schema.model_validate(reading.model_dump())

    async def complete_with_tools(
        self, tools: Sequence[ToolSpec], messages: Sequence[Message]
    ) -> ToolTurn:
        raise LLMError("down")


async def test_accepting_a_relaxation_re_plans_a_new_revision_with_the_relaxed_request(
    world: EvalWorld,
) -> None:
    reads = ReadsTheAccept()

    report = await evaluate(world, [OVERREACH], reads)

    played = only_run(report, "overreach")
    assert played.outcome is RunOutcome.PLANNED, played.error
    assert played.amendments_applied == 1, "accepting a relaxation is an amendment (ADR 0052)"
    assert played.revision is not None
    assert played.revision.number == 2
    assert played.revision.solver_status is not SolveStatus.INFEASIBLE
    [relaxed] = reads.accepted
    assert relaxed < 1.0
    assert [(p.property, p.passed) for p in played.properties] == [
        ("declares_infeasible: false", True),
        ("meets_clearance: SKU0005", True),
        ("diff_changes: clearance_targets", True),
    ]
    # The label states 95%; the accepted relaxation's value is what the request should hold.
    assert [(m.field, m.expected, m.matched) for m in played.extraction] == [
        ("marketing_budget", "20000", True),
        ("clearance_targets", f"SKU0005 {relaxed}", True),
    ]
    assert played.explanations[-1].revision == 2


async def test_accepting_a_relaxation_a_revision_does_not_have_fails_the_run(
    world: EvalWorld,
) -> None:
    feasible = Scenario.model_validate(
        {**PLAIN.model_dump(), "amendments": [{"accept_relaxation": True}]}
    )

    report = await evaluate(world, [feasible])

    played = only_run(report, "plain")
    assert played.outcome is RunOutcome.FAILED
    assert played.error == (
        "RuntimeError: amendment 1 accepts a relaxation, but plan revision 1 has no relaxation "
        "to accept"
    )
    assert played.amendments_applied == 0
    assert not report.scenarios[0].passed


class SlowProvider:
    """DownProvider that takes `delay` seconds to fail each call."""

    def __init__(self, delay: float) -> None:
        self.delay = delay
        self.down = DownProvider()

    async def complete_structured[T: BaseModel](
        self, schema: type[T], messages: Sequence[Message]
    ) -> T:
        await asyncio.sleep(self.delay)
        return await self.down.complete_structured(schema, messages)

    async def complete_with_tools(
        self, tools: Sequence[ToolSpec], messages: Sequence[Message]
    ) -> ToolTurn:
        await asyncio.sleep(self.delay)
        return await self.down.complete_with_tools(tools, messages)


async def test_session_time_ends_with_the_session_and_its_llm_time_is_the_wait_on_the_llm(
    world: EvalWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    scoring = runner._score

    async def slow_scoring(*args: Any, **kwargs: Any) -> Any:
        await asyncio.sleep(1.0)
        return await scoring(*args, **kwargs)

    monkeypatch.setattr(runner, "_score", slow_scoring)
    slow = SlowProvider(delay=0.05)

    report = await evaluate(world, [PLAIN], slow)

    plain = only_run(report, "plain")
    # Scoring the plan after the session is not session time (ADR 0062, ADR 0077).
    assert plain.duration_s - plain.session_s >= 1.0
    assert slow.down.calls > 0
    assert 0.05 * slow.down.calls <= plain.llm_s <= plain.session_s
    latency = metric(report, "session_latency_p50")
    assert latency.breakdown["llm_p50_s"] == round(plain.llm_s)
