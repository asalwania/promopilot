"""The committed scenario suite (SPEC §12.1, #56, ADR 0065): its group counts and as-of weeks,
what each group's scenarios expect, that each one tests what it says on the seed-42 world, and
that every brief but the vague ones is read to its labels with no LLM at all."""

from collections import Counter

import pytest

from promopilot.agents import read_context
from promopilot.agents.tools.inventory_status import pooled_stock
from promopilot.competitors.gaps import read_competitor_gaps
from promopilot.data import InMemoryRetailData
from promopilot.datagen import GeneratedDataset
from promopilot.domain import CompanyPolicy, PlanningRequest, Scope
from promopilot.evals import (
    SCENARIO_DIR,
    DeclaresInfeasible,
    DiffChanges,
    ExcludesRegion,
    KviResponsePresent,
    MeetsClearance,
    NoStrongSubstitutesTogether,
    RelaxationTouches,
    Scenario,
    ScenarioGroup,
    load_scenarios,
)
from promopilot.evals.behaviour import match_fields
from promopilot.evals.substitutes import strong_in_scope, strong_substitutes
from tests.unit.agents.fakes import DownProvider

G = ScenarioGroup
SPEC_COUNTS = {
    G.STANDARD_FESTIVE: 6,
    G.TIGHT_BUDGET: 4,
    G.OVERSTOCK_CLEARANCE: 4,
    G.COMPETITOR_PRICE_WAR: 4,
    G.REGIONAL_HOLIDAYS: 3,
    G.HEAVY_CANNIBALISATION: 3,
    G.VAGUE_OR_CONFLICTING: 3,
    G.INFEASIBLE_CONSTRAINTS: 2,
    G.MID_PLAN_AMENDMENTS: 3,
}
"""SPEC §12.1's count per group: the suite has at least these."""
AS_OF_WEEKS = {50, 62, 82, 104}
"""Diwali and Durga Puja 2025; Christmas 2025 and Pongal/Lohri 2026; off-season; Diwali,
Durga Puja and Christmas 2026 (ADR 0008, ADR 0065)."""
POLICY = CompanyPolicy()

SUITE = load_scenarios(SCENARIO_DIR)


def of(group: ScenarioGroup) -> list[Scenario]:
    return [scenario for scenario in SUITE if scenario.group is group]


def expects[T](scenario: Scenario, kind: type[T]) -> list[T]:
    return [prop for prop in scenario.expect if isinstance(prop, kind)]


def scope(scenario: Scenario) -> Scope:
    labels = scenario.labels
    assert labels.regions, f"{scenario.name} labels its regions"
    assert labels.categories, f"{scenario.name} labels its categories"
    return Scope(regions=labels.regions, categories=labels.categories)


# ---------------------------------------------------------------- counts and seasons


def test_the_suite_has_at_least_the_spec_count_in_every_group_and_30_in_all() -> None:
    counts = Counter(scenario.group for scenario in SUITE)

    assert {group: counts[group] for group in G} == {
        group: max(counts[group], SPEC_COUNTS[group]) for group in G
    }
    assert sum(counts.values()) >= 30


def test_the_suite_plans_at_four_as_of_weeks_with_seed_0() -> None:
    assert {scenario.as_of_week for scenario in SUITE} == AS_OF_WEEKS
    assert {scenario.seed for scenario in SUITE} == {0}


def test_five_scenarios_make_the_smoke_eval_across_five_groups_and_every_as_of_week() -> None:
    # CI plays these with the replay provider on every PR (ADR 0069).
    smoke = [scenario for scenario in SUITE if scenario.smoke]

    assert len(smoke) == 5
    assert len({scenario.group for scenario in smoke}) == 5
    assert {scenario.as_of_week for scenario in smoke} == AS_OF_WEEKS
    assert {G.INFEASIBLE_CONSTRAINTS, G.MID_PLAN_AMENDMENTS, G.VAGUE_OR_CONFLICTING} <= {
        scenario.group for scenario in smoke
    }


@pytest.mark.parametrize("season", ["Diwali", "Durga Puja", "Christmas", "Pongal", "off-season"])
def test_the_briefs_cover_each_season(season: str) -> None:
    assert any(season in scenario.brief for scenario in SUITE)


# ---------------------------------------------------------------- what each group expects


def declared_infeasible(scenario: Scenario) -> bool:
    return True in {prop.declares_infeasible for prop in expects(scenario, DeclaresInfeasible)}


def test_only_infeasible_scenarios_expect_a_declared_infeasibility() -> None:
    for scenario in SUITE:
        declared = {prop.declares_infeasible for prop in expects(scenario, DeclaresInfeasible)}
        if scenario.group is G.INFEASIBLE_CONSTRAINTS:
            assert declared == {True}, scenario.name
        elif scenario.group is G.OVERSTOCK_CLEARANCE and declared == {True}:
            # A clearance brief no plan can meet is declared infeasible, not cleared (ADR 0074).
            assert not expects(scenario, MeetsClearance), scenario.name
        else:
            assert True not in declared, scenario.name


def test_each_group_expects_the_properties_it_tests() -> None:
    for scenario in of(G.OVERSTOCK_CLEARANCE):
        cleared = {prop.meets_clearance for prop in expects(scenario, MeetsClearance)}
        targets = scenario.labels.clearance_targets or ()
        if declared_infeasible(scenario):
            assert targets, scenario.name
            continue
        assert cleared, scenario.name
        assert cleared == {target.sku_id for target in targets}, scenario.name
    for scenario in of(G.COMPETITOR_PRICE_WAR):
        assert expects(scenario, KviResponsePresent), scenario.name
        assert scenario.labels.kvi_price_tolerance is not None, scenario.name
    for scenario in of(G.REGIONAL_HOLIDAYS):
        outside = {prop.excludes_region for prop in expects(scenario, ExcludesRegion)}
        assert outside, scenario.name
        assert not outside & set(scope(scenario).regions), scenario.name
    for scenario in of(G.HEAVY_CANNIBALISATION):
        assert expects(scenario, NoStrongSubstitutesTogether), scenario.name
    for scenario in of(G.INFEASIBLE_CONSTRAINTS):
        assert expects(scenario, RelaxationTouches), scenario.name
        assert scenario.labels.clearance_targets, f"{scenario.name}: only clearance can bind"
    for scenario in of(G.MID_PLAN_AMENDMENTS):
        assert scenario.amendments, scenario.name
        assert any(isinstance(p, DiffChanges | ExcludesRegion) for p in scenario.expect), (
            scenario.name
        )
    for scenario in of(G.VAGUE_OR_CONFLICTING):
        assert scenario.clarified_fields, scenario.name


# ---------------------------------------------------------------- coherent on the seed-42 world


def test_every_labelled_window_ends_within_the_generated_horizon(
    default_dataset: GeneratedDataset,
) -> None:
    last_week = default_dataset.ground_truth.total_weeks - 1
    for scenario in SUITE:
        window = scenario.labels.promo_window
        if window is not None:  # the demo brief leaves the window to the Context agent
            assert window.end_week <= last_week, scenario.name


def test_every_named_sku_exists_and_every_clearance_sku_has_stock_to_clear(
    default_dataset: GeneratedDataset,
) -> None:
    known = set(default_dataset.products["sku_id"])
    for scenario in SUITE:
        targets = scenario.labels.clearance_targets or ()
        cleared = {prop.meets_clearance for prop in expects(scenario, MeetsClearance)}
        named = {target.sku_id for target in targets} | cleared
        assert named <= known, f"{scenario.name}: unknown {sorted(named - known)}"
        if not targets:
            continue
        snapshot = default_dataset.inventory
        stock = pooled_stock(
            snapshot[snapshot["snapshot_week"] == scenario.as_of_week - 1],
            default_dataset.stores,
            POLICY,
        )
        regions = {region.value for region in scope(scenario).regions}
        for target in targets:
            there = stock[(stock["sku_id"] == target.sku_id) & stock["region"].isin(regions)]
            assert len(there) == len(regions), f"{scenario.name}: {target.sku_id}"
            assert (there["available_stock"] > 0).all(), f"{scenario.name}: {target.sku_id}"


async def test_every_price_war_scope_has_an_undercut_kvi_at_its_week(
    default_dataset: GeneratedDataset,
) -> None:
    for scenario in of(G.COMPETITOR_PRICE_WAR):
        area = scope(scenario)
        gaps = await read_competitor_gaps(
            InMemoryRetailData(default_dataset, as_of_week=scenario.as_of_week),
            as_of_week=scenario.as_of_week,
            policy=POLICY,
            regions=area.regions,
            categories=area.categories,
            kvi_only=True,
        )
        assert any(gap.undercut for gap in gaps.gaps), scenario.name


def test_every_heavy_cannibalisation_scope_holds_strong_substitute_pairs(
    default_dataset: GeneratedDataset,
) -> None:
    truth = default_dataset.ground_truth
    strong = strong_substitutes(truth.substitute_pairs, truth.cross_effects)
    for scenario in of(G.HEAVY_CANNIBALISATION):
        found = strong_in_scope(strong, default_dataset.products, scope(scenario))
        assert len(found) >= 2, scenario.name


# ---------------------------------------------------------------- readable with no LLM


async def read_by_rules(dataset: GeneratedDataset, scenario: Scenario) -> PlanningRequest | None:
    """The request the Context agent reads when the LLM is down (ADR 0053), after the
    scenario's stated amendments: what an unrecorded replay plans on. An accepted relaxation is
    left out: its text comes from the plan, and the labels are what the scenario states."""
    reading = await read_context(
        scenario.brief,
        DownProvider(),
        InMemoryRetailData(dataset, as_of_week=scenario.as_of_week),
        policy=POLICY,
        amendments=scenario.stated_amendments,
        fallback=True,
    )
    return reading.request


@pytest.mark.parametrize(
    "scenario",
    [s for s in SUITE if s.group is not G.VAGUE_OR_CONFLICTING],
    ids=lambda scenario: scenario.name,
)
async def test_every_brief_but_the_vague_ones_is_read_to_its_labels_by_rules(
    default_dataset: GeneratedDataset, scenario: Scenario
) -> None:
    request = await read_by_rules(default_dataset, scenario)

    assert request is not None, "the rules would stop at a question the scenario does not answer"
    wrong = [m for m in match_fields(scenario.labels, request) if not m.matched]
    assert not wrong, [(m.field, m.expected, m.got) for m in wrong]
