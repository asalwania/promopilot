"""The eval report is written as timestamped JSON and Markdown with `latest` copies (SPEC §12.3,
ADR 0056)."""

from datetime import UTC, datetime
from pathlib import Path

from promopilot.domain import (
    ExplanationSource,
    FallbackReason,
    Region,
    SessionUsage,
    SolveStatus,
    Violation,
    ViolationCode,
)
from promopilot.evals.quality import assess
from promopilot.evals.report import (
    BestPlanSummary,
    Breach,
    ClarificationCheck,
    ConstraintCheck,
    DefaultPlanSummary,
    EvalReport,
    ExplainerRun,
    FieldMatch,
    InfeasibilityCheck,
    Metric,
    OracleScore,
    PlanQuality,
    PropertyResult,
    RevisionSummary,
    RuleBasedSummary,
    RunOutcome,
    RunResult,
    ScenarioResult,
    render_markdown,
    write_report,
)

FEAS = SolveStatus.FEASIBLE

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
        Metric(
            name="baseline_wape_region_sku",
            label="Baseline WAPE, region x SKU",
            value=0.14,
            count=0,
            of=0,
            direction="at_most",
            aim=0.25,
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
    assert "| Baseline WAPE, region x SKU | 14.0% | report (aim ≤ 25%) | — |" in markdown
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


# ---------------------------------------------------------------- agent behaviour (#55)

BEHAVED_RUN = FAILED_RUN.model_copy(
    update={
        "questions_asked": ("promo_window",),
        "extraction": (
            FieldMatch(field="regions", expected="North", got="North", matched=True),
            FieldMatch(field="marketing_budget", expected="200000", got="150000", matched=False),
        ),
        "flagged": ("objective",),
        "clarification": ClarificationCheck(
            named=("marketing_budget",), asked=(), flagged=(), passed=False
        ),
        "infeasibility": InfeasibilityCheck(
            revision=2, declared=False, relaxation=True, binding_named=False, passed=False
        ),
        "explanations": (
            ExplainerRun(revision=1, source=ExplanationSource.LLM, fallback_reason=None),
            ExplainerRun(
                revision=2,
                source=ExplanationSource.TEMPLATE,
                fallback_reason=FallbackReason.UNGROUNDED,
            ),
        ),
        "session_s": 12.34,
        "llm_s": 3.21,
        "usage": SessionUsage(calls=5, input_tokens=9_000, output_tokens=800, cost_inr=4.5),
    }
)
BEHAVED = REPORT.model_copy(
    update={
        "metrics": (
            *REPORT.metrics,
            Metric(
                name="session_latency_p50",
                label="P50 session time",
                value=12.34,
                count=1,
                of=1,
                unit="seconds",
            ),
            Metric(
                name="session_cost_p50",
                label="P50 session cost",
                value=4.5,
                count=1,
                of=1,
                unit="rupees",
            ),
        ),
        "scenarios": (REPORT.scenarios[0].model_copy(update={"runs": (BEHAVED_RUN,)}),),
    }
)


def test_the_markdown_shows_latency_and_cost_in_their_units() -> None:
    markdown = render_markdown(BEHAVED)

    assert "| P50 session time | 12.3 s (1 of 1) | report | — |" in markdown
    assert "| P50 session cost | ₹4.50 (1 of 1) | report | — |" in markdown


def test_the_markdown_has_an_agent_behaviour_row_per_run_and_its_failures() -> None:
    markdown = render_markdown(BEHAVED)

    assert "## Agent behaviour" in markdown
    assert (
        "| amend-drop-west | 1 | 1/2 | promo_window | objective | llm, template (ungrounded) "
        "| 12.3 s (LLM 3.2 s) | ₹4.50, 5 calls |"
    ) in markdown
    where = "- **amend-drop-west** run 1:"
    assert f"{where} read `marketing_budget` as 150000, labelled 200000" in markdown
    assert f"{where} neither asked about nor flagged marketing_budget" in markdown
    assert (
        f"{where} revision 2 is not declared infeasible and names no binding constraint" in markdown
    )


def test_session_time_and_the_latency_value_are_left_out_of_the_comparable_report() -> None:
    later = BEHAVED.model_copy(
        update={
            "metrics": tuple(
                metric.model_copy(update={"value": 99.0, "breakdown": {"max_s": 99}})
                if metric.unit == "seconds"
                else metric
                for metric in BEHAVED.metrics
            ),
            "scenarios": (
                BEHAVED.scenarios[0].model_copy(
                    update={
                        "runs": (BEHAVED_RUN.model_copy(update={"session_s": 99.0, "llm_s": 9.0}),)
                    }
                ),
            ),
        }
    )

    assert later.comparable() == BEHAVED.comparable()
    assert later.comparable()["metrics"][-1]["value"] == 4.5, "cost is deterministic in replay"


def test_the_markdown_compares_each_scored_plan_with_both_benchmarks(tmp_path: Path) -> None:
    scored = FAILED_RUN.model_copy(
        update={
            "quality": PlanQuality(
                objective=90_000.0,
                rule_based=RuleBasedSummary(
                    sku_ids=("SKU0001",),
                    dropped_sku_ids=("SKU0002",),
                    lines=2,
                    expected_promo_cost=19_000.0,
                    objective=-4_500.5,
                ),
                best=BestPlanSummary(
                    solver_status=SolveStatus.OPTIMAL,
                    lines=5,
                    sku_ids=("SKU0001", "SKU0003"),
                    objective=100_000.0,
                ),
                versus_rule_based="beats",
                regret=0.1,
                regret_rupees=10_000.0,
            )
        }
    )
    report = REPORT.model_copy(
        update={"scenarios": (REPORT.scenarios[0].model_copy(update={"runs": (scored,)}),)}
    )

    markdown = write_report(report, tmp_path).markdown.read_text(encoding="utf-8")

    assert "## Plan quality" in markdown
    # A report written before ADR 0078 has no default plan or breakdown.
    assert (
        "| amend-drop-west | 1 | ₹90,000 | ₹-4,500 (1 of 2 sellers kept) | — | ₹100,000 "
        "(OPTIMAL, 5 lines) | 10.0% | — | — | — | beats |"
    ) in markdown
    assert "Consistency needs at least two runs per scenario" in markdown


def _scored(quality: PlanQuality, run: int = 1) -> RunResult:
    return FAILED_RUN.model_copy(update={"run": run, "quality": quality})


def _quality(
    ours: float, default: float, best: float, best_status: SolveStatus = SolveStatus.OPTIMAL
) -> PlanQuality:
    return assess(
        objective=ours,
        status=SolveStatus.OPTIMAL,
        rule_based=RuleBasedSummary(
            sku_ids=("SKU0001",),
            dropped_sku_ids=(),
            lines=1,
            expected_promo_cost=1.0,
            objective=0.0,
        ),
        best=BestPlanSummary(
            solver_status=best_status, lines=5, sku_ids=("SKU0001",), objective=best
        ),
        default=DefaultPlanSummary(
            solver_status=SolveStatus.OPTIMAL, lines=4, sku_ids=("SKU0001",), objective=default
        ),
    )


def test_the_markdown_splits_each_regret_by_cause_and_flags_a_timed_out_best_plan(
    tmp_path: Path,
) -> None:
    runs = (
        _scored(_quality(ours=60_000.0, default=80_000.0, best=100_000.0)),
        _scored(_quality(ours=90_000.0, default=95_000.0, best=100_000.0), run=2),
        _scored(_quality(ours=97_000.0, default=97_000.0, best=10_000.0, best_status=FEAS), 3),
    )
    report = REPORT.model_copy(
        update={"scenarios": (REPORT.scenarios[0].model_copy(update={"runs": runs}),)}
    )

    markdown = write_report(report, tmp_path).markdown.read_text(encoding="utf-8")

    assert (
        "| Scenario | Run | Ours | Rule-based | Default sequence | Best | Regret | Model error "
        "| Planner | Timeouts | Against the baseline |"
    ) in markdown
    assert (
        "| amend-drop-west | 1 | ₹60,000 | ₹0 (1 of 1 sellers kept) | ₹80,000 (OPTIMAL, 4 "
        "lines) | ₹100,000 (OPTIMAL, 5 lines) | 40.0% | 20.0% | 20.0% | 0.0% | beats |"
    ) in markdown
    # Beating a best plan that timed out is not a win: flagged, and left out of the metric.
    assert "| -870.0% (best timed out: not counted) | 0.0% | 0.0% | -870.0% |" in markdown
    # Medians over the 2 counted runs, and each part's rupees.
    assert (
        "Regret by cause over the 2 counted runs (median, then ₹ in all): model error 12.5% "
        "(₹25,000), planner 12.5% (₹25,000), timeouts 0.0% (₹0)."
    ) in markdown


def test_each_run_writes_whether_it_passed_so_the_dashboard_never_re_derives_it(
    tmp_path: Path,
) -> None:
    """`/evals` shows a run's pass or fail as the report says (ADR 0072)."""
    dumped = REPORT.model_dump(mode="json")
    assert dumped["scenarios"][0]["runs"][0]["passed"] is False
    passing = FAILED_RUN.model_copy(
        update={"constraints": ConstraintCheck.PASSED, "properties": ()}
    )
    assert passing.model_dump(mode="json")["passed"] is True

    paths = write_report(REPORT, tmp_path)
    assert EvalReport.model_validate_json(paths.latest_json.read_bytes()) == REPORT
