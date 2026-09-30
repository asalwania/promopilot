"""`review_risks` flags a plan's over-concentration, heavy cannibalisation and stock-out risk on
its own tool outputs, deterministically, with actionable feedback (AG-04, ADR 0051)."""

from typing import Any

from promopilot.domain import (
    ClearanceTarget,
    Mechanism,
    MechanismOption,
    MechanismOutcome,
    Percentiles,
    PlanLine,
    PlanningRequest,
    PlanRevision,
    PlanRevisionLine,
    PlanSimulation,
    PromoWindow,
    Region,
    RiskCode,
    RiskFinding,
    Scope,
    SimulatedOutcomes,
    TargetSegment,
)
from promopilot.guardrails import (
    LineFacts,
    PlanFacts,
    RiskThresholds,
    SkuFacts,
    check_numeric_grounding,
    review_risks,
)

THRESHOLDS = RiskThresholds()


def request(
    regions: tuple[Region, ...] = (Region.NORTH, Region.WEST),
    categories: tuple[str, ...] = ("Snacks", "Beverages"),
) -> PlanningRequest:
    return PlanningRequest(
        as_of_week=100,
        scope=Scope(regions=regions, categories=categories),
        promo_window=PromoWindow(start_week=101, end_week=104),
        marketing_budget=100_000.0,
    )


class Line:
    """One hand-built plan line: its spend, category, cannibalisation and stock-out risk."""

    def __init__(
        self,
        sku_id: str,
        region: Region = Region.NORTH,
        *,
        promo_cost: float = 1_000.0,
        category: str = "Snacks",
        incremental_profit: float = 2_000.0,
        cannibalised_profit: float = 0.0,
        stockout_probability: float = 0.0,
    ) -> None:
        self.line = PlanLine(
            sku_id=sku_id,
            region=region,
            mechanism=Mechanism.PCT_OFF,
            depth_pct=20,
            duration_weeks=2,
            start_week=101,
            target_segment=TargetSegment.ALL_CUSTOMERS,
        )
        self.promo_cost = promo_cost
        self.category = category
        self.incremental_profit = incremental_profit
        self.cannibalised_profit = cannibalised_profit
        self.stockout_probability = stockout_probability

    def revision_line(self) -> PlanRevisionLine:
        option = MechanismOption(
            option=self.line,
            anchor_sku_id=self.line.sku_id,
            effective_price=80.0,
            units=100.0,
            revenue=8_000.0,
            gross_profit=2_000.0,
            margin=0.25,
            promo_cost=self.promo_cost,
            incremental_profit=self.incremental_profit,
            cannibalised_profit=self.cannibalised_profit,
            halo_profit=0.0,
            clearance_value=0.0,
            value=self.incremental_profit - self.cannibalised_profit,
        )
        return PlanRevisionLine(
            line=self.line,
            expected_units=100.0,
            promo_cost=self.promo_cost,
            expected_incremental_profit=self.incremental_profit,
            mechanism_comparison=(
                MechanismOutcome(mechanism=Mechanism.PCT_OFF, best=option, chosen=True),
            ),
        )

    def facts(self) -> LineFacts:
        return LineFacts(
            line=self.line,
            anchor=SkuFacts(
                category=self.category, base_price=100.0, unit_cost=50.0, overstocked=False
            ),
            expected_units=100.0,
            p90_units=120.0,
            available_stock=1_000.0,
            expected_revenue=8_000.0,
            expected_gross_profit=2_000.0,
            promo_cost=self.promo_cost,
        )


def ranged(value: float) -> Percentiles:
    return Percentiles(p10=value, p50=value, p90=value)


def outcomes() -> dict[str, Any]:
    return {
        "units": ranged(100.0),
        "revenue": ranged(8_000.0),
        "gross_profit": ranged(2_000.0),
        "margin": ranged(0.25),
        "promo_spend": ranged(1_000.0),
        "sell_through": None,
    }


def review(
    *lines: Line,
    scope: PlanningRequest | None = None,
    simulated: bool = True,
    thresholds: RiskThresholds = THRESHOLDS,
) -> tuple[RiskFinding, ...]:
    simulation = (
        PlanSimulation(
            n_runs=1_000,
            seed=0,
            lines=tuple(
                {
                    "sku_id": line.line.sku_id,
                    "region": line.line.region,
                    "stockout_probability": line.stockout_probability,
                    **outcomes(),
                }
                for line in lines
            ),
            total=SimulatedOutcomes(**outcomes()),
        )
        if simulated
        else None
    )
    revision = PlanRevision(
        number=1, lines=tuple(line.revision_line() for line in lines), simulation=simulation
    )
    facts = PlanFacts(lines=tuple(line.facts() for line in lines))
    return review_risks(revision, facts, scope or request(), thresholds)


def balanced(count: int = 8) -> list[Line]:
    """Lines spread evenly over both regions and both categories."""
    return [
        Line(
            f"S{number}",
            Region.NORTH if number % 2 else Region.WEST,
            category="Snacks" if number % 4 < 2 else "Beverages",
        )
        for number in range(count)
    ]


def codes(findings: tuple[RiskFinding, ...]) -> list[tuple[RiskCode, str | None, str | None]]:
    return [(finding.code, finding.sku_id, finding.category) for finding in findings]


def test_a_balanced_plan_with_no_risk_has_no_findings() -> None:
    assert review(*balanced()) == ()


def test_an_empty_plan_has_no_findings() -> None:
    assert review() == ()


# Over-concentration.


def test_a_line_taking_more_than_a_quarter_of_the_spend_is_over_concentrated() -> None:
    lines = balanced()
    lines[0] = Line("S0", Region.WEST, category="Snacks", promo_cost=4_000.0)

    [finding] = review(*lines)

    assert finding.code is RiskCode.OVER_CONCENTRATION
    assert (finding.sku_id, finding.region) == ("S0", Region.WEST)
    assert finding.actual == 4_000.0 / 11_000.0
    assert finding.limit == 0.25
    assert "36.4%" in finding.message
    assert finding.message.startswith("S0 in West (PCT_OFF at 20%): ")
    assert "S0" in finding.feedback


def test_line_concentration_is_not_checked_when_too_few_lines_to_spread_the_spend() -> None:
    # Three lines: one of them must take at least a third of the spend.
    lines = [
        Line("S0", Region.NORTH, category="Snacks", promo_cost=2_000.0),
        Line("S1", Region.WEST, category="Beverages", promo_cost=1_500.0),
        Line("S2", Region.WEST, category="Beverages"),
    ]

    assert review(*lines) == ()


def test_a_category_taking_over_80_percent_of_the_spend_is_over_concentrated() -> None:
    lines = [Line(f"S{n}", Region.NORTH if n % 2 else Region.WEST) for n in range(9)]
    lines.append(Line("B1", Region.NORTH, category="Beverages"))

    [finding] = review(*lines)

    assert finding.code is RiskCode.OVER_CONCENTRATION
    assert finding.category == "Snacks"
    assert finding.sku_id is None
    assert finding.actual == 0.9
    assert finding.limit == 0.8


def test_a_single_category_scope_is_not_over_concentrated_in_it() -> None:
    lines = [Line(f"S{n}", Region.NORTH if n % 2 else Region.WEST) for n in range(8)]

    assert review(*lines, scope=request(categories=("Snacks",))) == ()


def test_a_region_taking_over_80_percent_of_the_spend_is_over_concentrated() -> None:
    lines = [
        Line(f"S{n}", Region.NORTH, category="Snacks" if n % 2 else "Beverages") for n in range(9)
    ]
    lines.append(Line("W1", Region.WEST))

    [finding] = review(*lines)

    assert finding.code is RiskCode.OVER_CONCENTRATION
    assert (finding.region, finding.sku_id, finding.category) == (Region.NORTH, None, None)


def test_a_single_region_scope_is_not_over_concentrated_in_it() -> None:
    lines = [Line(f"S{n}", category="Snacks" if n % 2 else "Beverages") for n in range(8)]

    assert review(*lines, scope=request(regions=(Region.NORTH,))) == ()


# Heavy cannibalisation.


def test_a_line_losing_half_its_incremental_profit_to_cannibalisation_is_flagged() -> None:
    lines = balanced()
    lines[3] = Line(
        "S3", Region.NORTH, category="Beverages", incremental_profit=2_880.0,
        cannibalised_profit=2_489.0,
    )  # fmt: skip
    lines[5] = Line(
        "S5", Region.NORTH, category="Beverages", incremental_profit=2_000.0,
        cannibalised_profit=999.0,
    )  # fmt: skip

    [finding] = review(*lines)

    assert finding.code is RiskCode.HEAVY_CANNIBALISATION
    assert (finding.sku_id, finding.region) == ("S3", Region.NORTH)
    assert finding.actual == 2_489.0 / 2_880.0
    assert finding.limit == 0.5
    assert "86.4%" in finding.message
    assert "₹2,489" in finding.message
    assert finding.message.startswith("S3 in North (PCT_OFF at 20%): ")


def test_exactly_half_is_heavy_cannibalisation() -> None:
    lines = balanced()
    lines[1] = Line("S1", Region.NORTH, incremental_profit=2_000.0, cannibalised_profit=1_000.0)

    assert codes(review(*lines)) == [(RiskCode.HEAVY_CANNIBALISATION, "S1", None)]


def test_a_line_without_positive_incremental_profit_is_not_judged_on_cannibalisation() -> None:
    # It is in the plan for its halo or clearance value, which the optimiser already weighed.
    lines = balanced()
    lines[1] = Line("S1", Region.NORTH, incremental_profit=-500.0, cannibalised_profit=900.0)

    assert review(*lines) == ()


# Stock-out risk.


def test_a_line_that_runs_out_in_a_fifth_of_the_runs_is_a_stockout_risk() -> None:
    lines = balanced()
    lines[2] = Line("S2", Region.WEST, category="Beverages", stockout_probability=0.2)
    lines[4] = Line("S4", Region.WEST, stockout_probability=0.19)

    [finding] = review(*lines)

    assert finding.code is RiskCode.STOCKOUT_RISK
    assert (finding.sku_id, finding.region) == ("S2", Region.WEST)
    assert finding.actual == 0.2
    assert "20%" in finding.message
    assert finding.message.startswith("S2 in West (PCT_OFF at 20%) runs out of stock")


def test_an_unsimulated_plan_has_no_stockout_findings() -> None:
    lines = balanced()
    lines[2] = Line("S2", Region.WEST, category="Beverages", stockout_probability=0.9)

    assert review(*lines, simulated=False) == ()


# Order, thresholds and grounding.


def test_findings_come_concentration_then_cannibalisation_then_stockout() -> None:
    lines = balanced()
    lines[0] = Line("S0", Region.WEST, promo_cost=4_000.0, stockout_probability=0.5)
    lines[1] = Line("S1", Region.NORTH, incremental_profit=100.0, cannibalised_profit=90.0)

    assert codes(review(*lines)) == [
        (RiskCode.OVER_CONCENTRATION, "S0", None),
        (RiskCode.HEAVY_CANNIBALISATION, "S1", None),
        (RiskCode.STOCKOUT_RISK, "S0", None),
    ]


def test_thresholds_are_configurable() -> None:
    lines = balanced()
    lines[2] = Line("S2", Region.WEST, category="Beverages", stockout_probability=0.12)

    assert review(*lines) == ()
    assert codes(review(*lines, thresholds=RiskThresholds(stockout_probability=0.1))) == [
        (RiskCode.STOCKOUT_RISK, "S2", None)
    ]


def test_every_number_in_the_feedback_is_one_its_message_shows() -> None:
    lines = balanced()
    lines[0] = Line("S0", Region.WEST, promo_cost=4_000.0, stockout_probability=0.37)
    lines[1] = Line("S1", Region.NORTH, incremental_profit=1_234.0, cannibalised_profit=987.0)
    lines.append(Line("S9", Region.NORTH, promo_cost=150_000.0))

    findings = review(*lines)

    assert len(findings) >= 3
    for finding in findings:
        assert check_numeric_grounding(finding.feedback, finding.message).grounded


def test_feedback_names_the_lever_the_planner_has_for_each_finding() -> None:
    # A SKU's finding leads with capping its depth below the plan line's, and falls back to
    # leaving it out (ADR 0084, ADR 0059).
    lines = balanced()
    lines[0] = Line("S0", Region.WEST, promo_cost=4_000.0, stockout_probability=0.37)
    lines[1] = Line("S1", Region.NORTH, incremental_profit=1_234.0, cannibalised_profit=987.0)

    findings = review(*lines)

    assert {finding.code for finding in findings} == set(RiskCode)
    for finding in findings:
        if finding.sku_id is not None:
            feedback = finding.feedback.lower()
            cap = f"cap {finding.sku_id.lower()}'s depth below 20%"
            lever = f"{finding.sku_id.lower()} out with generate_candidates' exclude_sku_ids"
            assert cap in feedback
            assert "generate_candidates' sku_limits" in feedback
            assert lever in feedback
            assert feedback.index(cap) < feedback.index(lever)
        assert "compare_mechanisms" not in finding.feedback
        assert "generate_candidates' sku_ids" not in finding.feedback


def test_a_clearance_target_is_not_sent_out_of_the_plan() -> None:
    # exclude_sku_ids refuses a clearance target of the brief: the SKU stays (ADR 0059).
    lines = balanced()
    lines[0] = Line("S0", Region.WEST, promo_cost=4_000.0, stockout_probability=0.37)
    lines[1] = Line("S1", Region.NORTH, incremental_profit=1_234.0, cannibalised_profit=987.0)
    cleared = request().model_copy(
        update={
            "clearance_targets": (
                ClearanceTarget(sku_id="S0", sell_through=0.5),
                ClearanceTarget(sku_id="S1", sell_through=0.5),
            )
        }
    )

    findings = review(*lines, scope=cleared)

    assert {finding.sku_id for finding in findings} == {"S0", "S1"}
    for finding in findings:
        assert "exclude_sku_ids" not in finding.feedback
        assert "sku_limits" not in finding.feedback  # it refuses a clearance target too
        assert f"{finding.sku_id} is a clearance target of the brief" in finding.feedback
        assert check_numeric_grounding(finding.feedback, finding.message).grounded
