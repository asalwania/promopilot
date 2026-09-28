"""The eval report is written as timestamped JSON and Markdown with `latest` copies (SPEC §12.3,
ADR 0056)."""

from datetime import UTC, datetime
from pathlib import Path

from promopilot.domain import Region, SolveStatus, Violation, ViolationCode
from promopilot.evals.report import (
    Breach,
    ConstraintCheck,
    EvalReport,
    Metric,
    OracleScore,
    PropertyResult,
    RevisionSummary,
    RunOutcome,
    RunResult,
    ScenarioResult,
    write_report,
)

FAILED_RUN = RunResult(
    run=1,
    outcome=RunOutcome.PLANNED,
    revision=RevisionSummary(
        number=2,
        lines=3,
        regions=(Region.NORTH,),
        solver_status=SolveStatus.OPTIMAL,
        objective=1_000.0,
        promo_cost=21_000.0,
        marketing_budget=20_000.0,
    ),
    constraints=ConstraintCheck.FAILED,
    violations=(Violation(code=ViolationCode.BUDGET, message="Promo cost exceeds the budget"),),
    oracle=OracleScore(
        incremental_profit=500.0,
        clearance_value=0.0,
        promo_cost=22_000.0,
        blended_margin=0.2,
        stock_capped_lines=1,
        breaches=(Breach.PROMO_COST_OVER_BUDGET, Breach.DEMAND_OVER_STOCK),
    ),
    properties=(
        PropertyResult(
            property="excludes_region: West", passed=False, detail="1 plan line in West"
        ),
    ),
    duration_s=1.5,
)
REPORT = EvalReport(
    generated_at=datetime(2026, 9, 28, 14, 15, 3, tzinfo=UTC),
    provider="replay",
    world_seed=42,
    runs_per_scenario=1,
    planning_settings={"optimizer_seed": 0},
    metrics=(
        Metric(
            name="constraint_satisfaction",
            label="Constraint satisfaction",
            value=0.0,
            count=0,
            of=1,
            target=1.0,
            direction="at_least",
            passed=False,
        ),
        Metric(
            name="oracle_breach_rate",
            label="Oracle breach rate",
            value=1.0,
            count=1,
            of=1,
            breakdown={"promo_cost_over_budget": 1},
        ),
    ),
    scenarios=(
        ScenarioResult(
            name="amend-drop-west",
            group="mid_plan_amendments",
            as_of_week=104,
            seed=0,
            runs=(FAILED_RUN,),
            passed=False,
        ),
    ),
)


def test_the_report_is_written_with_a_timestamp_and_as_latest(tmp_path: Path) -> None:
    paths = write_report(REPORT, tmp_path / "reports")

    assert paths.json.name == "20260928T141503Z.json"
    assert paths.markdown.name == "20260928T141503Z.md"
    assert paths.latest_json.read_bytes() == paths.json.read_bytes()
    assert paths.latest_markdown.read_bytes() == paths.markdown.read_bytes()
    assert EvalReport.model_validate_json(paths.latest_json.read_bytes()) == REPORT


def test_the_markdown_shows_each_metric_against_its_target_and_every_failure(
    tmp_path: Path,
) -> None:
    markdown = write_report(REPORT, tmp_path).markdown.read_text(encoding="utf-8")

    assert "| Constraint satisfaction | 0.0% (0 of 1) | ≥ 100% | **fail** |" in markdown
    assert "| Oracle breach rate | 100.0% (1 of 1) | report | — |" in markdown
    assert "- Oracle breach rate: promo_cost_over_budget 1" in markdown
    assert (
        "| amend-drop-west | mid_plan_amendments | 1 | planned | rev 2: 3 lines, OPTIMAL "
        "| failed | promo_cost_over_budget, demand_over_stock | 0/1 | **fail** |"
    ) in markdown
    assert "- **amend-drop-west** run 1: Promo cost exceeds the budget" in markdown
    assert (
        "- **amend-drop-west** run 1: expected `excludes_region: West`: 1 plan line in West"
        in markdown
    )


def test_only_timing_is_left_out_of_the_comparable_report() -> None:
    later = REPORT.model_copy(
        update={
            "generated_at": datetime(2026, 9, 29, tzinfo=UTC),
            "scenarios": (
                REPORT.scenarios[0].model_copy(
                    update={"runs": (FAILED_RUN.model_copy(update={"duration_s": 9.0}),)}
                ),
            ),
        }
    )

    assert later.comparable() == REPORT.comparable()
    assert "provider" in REPORT.comparable()
