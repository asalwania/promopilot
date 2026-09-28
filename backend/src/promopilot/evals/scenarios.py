"""Eval scenarios (SPEC §12.1, ADR 0056): one YAML file per scenario in `evals/scenarios/`.

A scenario is a brief, the answers the manager gives if the Context agent asks (by question id,
which is the field name, ADR 0048), the amendments made once a plan is waiting for approval, in
order, the as-of week it is planned at (ADR 0008), the seed its sessions plan with, its group,
the planning-request fields the brief states (labels), and the properties its outcome is
expected to have: never an exact plan.
"""

from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from promopilot.domain import ClearanceTarget, ConstraintKind, PromoWindow, Region

SCENARIO_DIR = Path("evals/scenarios")
"""The committed scenario suite, relative to backend/."""


class ScenarioGroup(StrEnum):
    """The nine SPEC §12.1 groups."""

    STANDARD_FESTIVE = "standard_festive"
    TIGHT_BUDGET = "tight_budget"
    OVERSTOCK_CLEARANCE = "overstock_clearance"
    COMPETITOR_PRICE_WAR = "competitor_price_war"
    REGIONAL_HOLIDAYS = "regional_holidays"
    HEAVY_CANNIBALISATION = "heavy_cannibalisation"
    VAGUE_OR_CONFLICTING = "vague_or_conflicting"
    INFEASIBLE_CONSTRAINTS = "infeasible_constraints"
    MID_PLAN_AMENDMENTS = "mid_plan_amendments"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------- expected properties
# A closed vocabulary: each property is a one-key mapping in the YAML (ADR 0056). #55 adds
# more as the scenario suite needs them.


class AsksClarification(_Frozen):
    """The Context agent asked about this field (its question id) at some point."""

    asks_clarification: str = Field(min_length=1)

    def describe(self) -> str:
        return f"asks_clarification: {self.asks_clarification}"


class DeclaresInfeasible(_Frozen):
    """The final plan revision is infeasible (true), or is not (false)."""

    declares_infeasible: bool

    def describe(self) -> str:
        return f"declares_infeasible: {str(self.declares_infeasible).lower()}"


class ExcludesRegion(_Frozen):
    """The final plan revision has no plan line in this region."""

    excludes_region: Region

    def describe(self) -> str:
        return f"excludes_region: {self.excludes_region.value}"


class MeetsClearance(_Frozen):
    """The final plan revision has no clearance shortfall for this SKU."""

    meets_clearance: str = Field(min_length=1)

    def describe(self) -> str:
        return f"meets_clearance: {self.meets_clearance}"


class RelaxationTouches(_Frozen):
    """The final plan revision's relaxation changes a constraint of this kind (#55)."""

    relaxation_touches: ConstraintKind

    def describe(self) -> str:
        return f"relaxation_touches: {self.relaxation_touches.value}"


class FlagsAssumption(_Frozen):
    """The final reading of the brief flags this field's assumption (ADR 0048), such as a
    minimum margin below company policy's floor (#55)."""

    flags_assumption: str = Field(min_length=1)

    def describe(self) -> str:
        return f"flags_assumption: {self.flags_assumption}"


class DiffChanges(_Frozen):
    """The final plan revision's diff lists a change to this planning-request field, such as
    `scope.regions` or `marketing_budget` (ADR 0052, #55)."""

    diff_changes: str = Field(min_length=1)

    def describe(self) -> str:
        return f"diff_changes: {self.diff_changes}"


class KviResponsePresent(_Frozen):
    """The planner's response to the undercut KVIs in scope, recomputed from the competitor
    gaps for the final plan, is in its notes and the plan summary (F-08 AC2, #55)."""

    kvi_response_present: Literal[True]

    def describe(self) -> str:
        return "kvi_response_present: true"


class NoStrongSubstitutesTogether(_Frozen):
    """The final plan revision promotes no two strong true substitutes in scope together: in the
    same region, with a common promo week and a common target segment (#56, ADR 0065)."""

    no_strong_substitutes_together: Literal[True]

    def describe(self) -> str:
        return "no_strong_substitutes_together: true"


type ExpectedProperty = (
    AsksClarification
    | DeclaresInfeasible
    | ExcludesRegion
    | MeetsClearance
    | RelaxationTouches
    | FlagsAssumption
    | DiffChanges
    | KviResponsePresent
    | NoStrongSubstitutesTogether
)


# ---------------------------------------------------------------- the scenario


class RequestLabels(_Frozen):
    """The planning-request fields the scenario states, as the final request should read them
    once the answers and amendments are in; a field left out is not scored (#55)."""

    regions: tuple[Region, ...] | None = None
    categories: tuple[str, ...] | None = None
    sku_ids: tuple[str, ...] | None = None
    promo_window: PromoWindow | None = None
    marketing_budget: float | None = Field(default=None, gt=0)
    min_margin: float | None = Field(default=None, ge=0, lt=1)
    clearance_targets: tuple[ClearanceTarget, ...] | None = None
    regional_budget_caps: dict[Region, float] | None = None
    kvi_price_tolerance: float | None = Field(default=None, ge=0, lt=1)
    max_promoted_skus_per_category_per_region: int | None = Field(default=None, ge=1)


class Scenario(_Frozen):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    group: ScenarioGroup
    brief: str = Field(min_length=1)
    as_of_week: int = Field(ge=1)
    """The week the scenario treats as today (ADR 0008)."""
    seed: int = Field(ge=0)
    """The optimiser's and the simulation's seed for every session of the scenario."""
    clarifications: dict[str, str] = Field(default_factory=dict)
    """Answers by question id, given only when that question is asked."""
    amendments: tuple[str, ...] = ()
    """Made in order, each once the session waits for approval."""
    labels: RequestLabels = RequestLabels()
    expect: tuple[ExpectedProperty, ...] = ()

    @property
    def clarified_fields(self) -> tuple[str, ...]:
        """The fields its `asks_clarification` and `flags_assumption` properties name."""
        named: list[str] = []
        for prop in self.expect:
            if isinstance(prop, AsksClarification):
                named.append(prop.asks_clarification)
            elif isinstance(prop, FlagsAssumption):
                named.append(prop.flags_assumption)
        return tuple(named)

    @model_validator(mode="after")
    def _window_after_as_of_week(self) -> Self:
        window = self.labels.promo_window
        if window is not None and window.start_week <= self.as_of_week:
            raise ValueError("the labelled promo window must start after the as-of week (ADR 0008)")
        return self

    @model_validator(mode="after")
    def _a_vague_scenario_names_what_to_clarify(self) -> Self:
        if self.group is ScenarioGroup.VAGUE_OR_CONFLICTING and not self.clarified_fields:
            raise ValueError(
                "a vague or conflicting scenario expects asks_clarification or flags_assumption "
                "on at least one field (#55)"
            )
        return self


def load_scenario(path: Path) -> Scenario:
    """The scenario in a YAML file; its name must be the file's name. Raises
    `pydantic.ValidationError` for an invalid scenario."""
    scenario = Scenario.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    if scenario.name != path.stem:
        raise ValueError(f"scenario {scenario.name!r} must be in {scenario.name}.yaml, not {path}")
    return scenario


def load_scenarios(directory: Path) -> list[Scenario]:
    """Every `*.yaml` scenario in `directory`, in name order."""
    return [load_scenario(path) for path in sorted(directory.glob("*.yaml"))]
