"""Eval scenarios: YAML files validated into a Scenario (SPEC §12.1, ADR 0056)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from promopilot.domain import PromoWindow, Region
from promopilot.evals import (
    SCENARIO_DIR,
    AcceptRelaxation,
    AsksClarification,
    DeclaresInfeasible,
    DiffChanges,
    ExcludesRegion,
    MeetsClearance,
    NoStrongSubstitutesTogether,
    Scenario,
    ScenarioGroup,
    load_scenario,
    load_scenarios,
)

FULL = """\
name: amend-drop-west
group: mid_plan_amendments
brief: "Diwali push for Snacks in North and West, budget ₹2 lakh"
as_of_week: 104
seed: 3
clarifications:
  min_margin: "Keep it above 20%"
amendments:
  - "Drop West"
labels:
  regions: [North]
  categories: [Snacks]
  promo_window: {start_week: 108, end_week: 109}
  marketing_budget: 200000
expect:
  - asks_clarification: min_margin
  - declares_infeasible: false
  - excludes_region: West
  - meets_clearance: SKU0002
"""


def write(directory: Path, name: str, text: str) -> Path:
    path = directory / f"{name}.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_a_scenario_file_loads_with_its_steps_labels_and_expected_properties(
    tmp_path: Path,
) -> None:
    scenario = load_scenario(write(tmp_path, "amend-drop-west", FULL))

    assert scenario.name == "amend-drop-west"
    assert scenario.group is ScenarioGroup.MID_PLAN_AMENDMENTS
    assert scenario.brief.endswith("₹2 lakh")
    assert (scenario.as_of_week, scenario.seed) == (104, 3)
    assert scenario.clarifications == {"min_margin": "Keep it above 20%"}
    assert scenario.amendments == ("Drop West",)
    assert scenario.labels.regions == (Region.NORTH,)
    assert scenario.labels.promo_window == PromoWindow(start_week=108, end_week=109)
    assert scenario.labels.marketing_budget == 200_000
    assert scenario.expect == (
        AsksClarification(asks_clarification="min_margin"),
        DeclaresInfeasible(declares_infeasible=False),
        ExcludesRegion(excludes_region=Region.WEST),
        MeetsClearance(meets_clearance="SKU0002"),
    )
    assert [prop.describe() for prop in scenario.expect] == [
        "asks_clarification: min_margin",
        "declares_infeasible: false",
        "excludes_region: West",
        "meets_clearance: SKU0002",
    ]


def test_a_minimal_scenario_needs_only_its_name_group_brief_week_and_seed(tmp_path: Path) -> None:
    text = "name: plain\ngroup: tight_budget\nbrief: Snacks, ₹50k\nas_of_week: 60\nseed: 0\n"

    scenario = load_scenario(write(tmp_path, "plain", text))

    assert scenario.clarifications == {}
    assert scenario.amendments == ()
    assert scenario.expect == ()
    assert scenario.smoke is False


def test_a_scenario_can_be_tagged_for_the_smoke_eval(tmp_path: Path) -> None:
    text = "name: plain\ngroup: tight_budget\nbrief: Snacks, ₹50k\nas_of_week: 60\nseed: 0\n"

    scenario = load_scenario(write(tmp_path, "plain", text + "smoke: true\n"))

    assert scenario.smoke is True


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        (("group: mid_plan_amendments", "group: festive"), "group"),
        (("  - excludes_region: West", "  - excludes_region: Mars"), "excludes_region"),
        (("  - meets_clearance: SKU0002", "  - promotes_everything: true"), "expect"),
        (("seed: 3", "seed: 3\nnotes: typo"), "notes"),
        (("as_of_week: 104", "as_of_week: 0"), "as_of_week"),
    ],
)
def test_an_invalid_scenario_is_refused(
    tmp_path: Path, change: tuple[str, str], problem: str
) -> None:
    path = write(tmp_path, "amend-drop-west", FULL.replace(*change))

    with pytest.raises(ValidationError, match=problem):
        load_scenario(path)


ACCEPTS = FULL.replace('  - "Drop West"\n', '  - "Drop West"\n  - accept_relaxation: true\n')


def test_an_amendment_can_accept_the_latest_revisions_relaxation(tmp_path: Path) -> None:
    scenario = load_scenario(write(tmp_path, "amend-drop-west", ACCEPTS))

    assert scenario.amendments == ("Drop West", AcceptRelaxation(accept_relaxation=True))
    assert scenario.stated_amendments == ("Drop West",)


@pytest.mark.parametrize(
    ("accept", "problem"),
    [
        ("  - accept_relaxation: false\n", "accept_relaxation"),
        ("  - accept_relaxation: true\n    note: typo\n", "note"),
        ("  - accept: true\n", "accept"),
    ],
)
def test_an_amendment_accepts_a_relaxation_only_as_accept_relaxation_true(
    tmp_path: Path, accept: str, problem: str
) -> None:
    text = FULL.replace('  - "Drop West"\n', f'  - "Drop West"\n{accept}')

    with pytest.raises(ValidationError, match=problem):
        load_scenario(write(tmp_path, "amend-drop-west", text))


def test_the_demo_scenario_accepts_its_relaxation_and_expects_a_feasible_revision() -> None:
    demo = load_scenario(SCENARIO_DIR / "demo-budget-cut-drop-west.yaml")

    assert demo.amendments == (
        "Budget cut to ₹6 lakh",
        "Drop West",
        AcceptRelaxation(accept_relaxation=True),
    )
    assert DeclaresInfeasible(declares_infeasible=False) in demo.expect
    assert DiffChanges(diff_changes="clearance_targets") in demo.expect


def test_the_strong_substitutes_property_loads(tmp_path: Path) -> None:
    text = FULL.replace("  - meets_clearance: SKU0002", "  - no_strong_substitutes_together: true")

    scenario = load_scenario(write(tmp_path, "amend-drop-west", text))

    assert scenario.expect[-1] == NoStrongSubstitutesTogether(no_strong_substitutes_together=True)
    assert scenario.expect[-1].describe() == "no_strong_substitutes_together: true"


def test_a_labelled_promo_window_must_start_after_the_as_of_week(tmp_path: Path) -> None:
    text = FULL.replace("start_week: 108", "start_week: 104")

    with pytest.raises(ValidationError, match="after the as-of week"):
        load_scenario(write(tmp_path, "amend-drop-west", text))


def test_a_scenarios_name_is_its_file_name(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"amend-drop-west.*other"):
        load_scenario(write(tmp_path, "other", FULL))


def test_the_scenarios_of_a_directory_load_in_name_order(tmp_path: Path) -> None:
    for name in ("b-second", "a-first"):
        write(tmp_path, name, FULL.replace("amend-drop-west", name))
    (tmp_path / "README.md").write_text("not a scenario", encoding="utf-8")

    assert [scenario.name for scenario in load_scenarios(tmp_path)] == ["a-first", "b-second"]


def test_every_committed_scenario_validates() -> None:
    scenarios = load_scenarios(SCENARIO_DIR)

    assert scenarios, f"no scenario in {SCENARIO_DIR}"
    assert all(isinstance(scenario, Scenario) for scenario in scenarios)
