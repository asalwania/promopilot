"""`--check` (the CI smoke eval, ADR 0069) fails a report on what must never regress: a run
that did not plan, a broken constraint or expected property, a vague or infeasible scenario
handled wrongly, and any request no cassette held. Ratio metrics never fail it."""

from datetime import UTC, datetime

from promopilot.domain import Violation, ViolationCode
from promopilot.evals.check import report_problems
from promopilot.evals.report import (
    ClarificationCheck,
    ConstraintCheck,
    EvalReport,
    FieldMatch,
    InfeasibilityCheck,
    Metric,
    PropertyResult,
    RunOutcome,
    RunResult,
    ScenarioResult,
)

GOOD = RunResult(
    run=1,
    outcome=RunOutcome.PLANNED,
    constraints=ConstraintCheck.PASSED,
    properties=(PropertyResult(property="excludes_region: West", passed=True, detail="none"),),
    # Fallbacks replayed from a recording are what the recording did: not a problem.
    fallbacks=("explainer: ungrounded",),
    extraction=(FieldMatch(field="regions", expected="North", got="South", matched=False),),
)
MISSED_TARGET = Metric(
    name="plan_quality",
    label="Plan quality",
    value=0.0,
    count=0,
    of=1,
    target=0.9,
    direction="at_least",
    passed=False,
)


def report(*runs: RunResult, name: str = "smoke") -> EvalReport:
    return EvalReport(
        generated_at=datetime(2026, 9, 29, tzinfo=UTC),
        provider="replay",
        world_seed=42,
        runs_per_scenario=len(runs),
        planning_settings={},
        metrics=(MISSED_TARGET,),
        scenarios=(
            ScenarioResult(
                name=name,
                group="standard_festive",
                as_of_week=104,
                seed=0,
                runs=runs,
                passed=all(played.passed for played in runs),
            ),
        ),
    )


def test_a_report_whose_runs_all_planned_and_passed_has_no_problem() -> None:
    # A missed ratio target and an extraction mismatch are reported, never checked.
    assert report_problems(report(GOOD)) == []


def test_a_run_that_failed_or_is_still_asking_is_a_problem() -> None:
    failed = GOOD.model_copy(update={"outcome": RunOutcome.FAILED, "error": "Boom: no plan"})
    asking = GOOD.model_copy(
        update={
            "run": 2,
            "outcome": RunOutcome.AWAITING_CLARIFICATION,
            "questions_asked": ("marketing_budget",),
        }
    )

    problems = report_problems(report(failed, asking))

    assert problems == [
        "smoke run 1: failed: Boom: no plan",
        "smoke run 2: ended with no plan, still asking (marketing_budget)",
    ]


def test_a_broken_constraint_or_expected_property_is_a_problem() -> None:
    broken = GOOD.model_copy(
        update={
            "constraints": ConstraintCheck.FAILED,
            "violations": (
                Violation(code=ViolationCode.BUDGET, message="Promo cost exceeds the budget"),
            ),
            "properties": (
                PropertyResult(property="excludes_region: West", passed=False, detail="2 lines"),
            ),
        }
    )

    assert report_problems(report(broken)) == [
        "smoke run 1: Promo cost exceeds the budget",
        "smoke run 1: expected `excludes_region: West`: 2 lines",
    ]


def test_a_vague_scenario_that_neither_asked_nor_flagged_is_a_problem() -> None:
    silent = GOOD.model_copy(
        update={
            "clarification": ClarificationCheck(
                named=("marketing_budget",), asked=(), flagged=(), passed=False
            )
        }
    )

    assert report_problems(report(silent)) == [
        "smoke run 1: neither asked about nor flagged marketing_budget"
    ]


def test_an_infeasible_scenario_handled_wrongly_is_a_problem() -> None:
    undeclared = GOOD.model_copy(
        update={
            "infeasibility": InfeasibilityCheck(
                revision=1, declared=False, relaxation=False, binding_named=True, passed=False
            )
        }
    )

    assert report_problems(report(undeclared)) == [
        "smoke run 1: revision 1 is not declared infeasible and proposes no relaxation"
    ]


def test_every_cassette_miss_is_a_problem_naming_the_requests() -> None:
    missed = GOOD.model_copy(update={"cassette_misses": ("a" * 64, "b" * 64)})

    assert report_problems(report(missed)) == [
        f"smoke run 1: 2 requests no cassette holds: {'a' * 64}, {'b' * 64}"
    ]


def test_a_report_with_no_scenario_is_a_problem() -> None:
    empty = report(GOOD).model_copy(update={"scenarios": ()})

    assert report_problems(empty) == ["no scenario ran"]
