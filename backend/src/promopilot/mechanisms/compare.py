"""Compare mechanisms for a SKU in a region (SPEC F-02, ADR 0041).

`compare` reads a generated candidate set (ADR 0035), so every mechanism is judged on the
numbers the optimiser chose from: the demand model's expected units and money, with
cannibalisation, halo and clearance value. For each mechanism it picks the option with the
highest value (incremental profit - cannibalisation + halo + clearance value, ADR 0036) over
every depth, duration, start week and target segment that survived the per-line rules. It
ranks the mechanisms by that value. A plan line's own mechanism is shown with the plan line
itself. A mechanism whose every option broke a rule is listed last, with the rules. BUNDLE is
compared only with a detected complement as the partner (F-02 AC2).
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cached_property

import numpy as np
import pandas as pd

from promopilot.domain import (
    Mechanism,
    MechanismOption,
    MechanismOutcome,
    PlanLine,
    PruneReason,
    Region,
)
from promopilot.economics import effective_unit_price
from promopilot.models.relations import RelationLookup
from promopilot.optimizer import PromoOptions

_NUMBERS = (
    "units",
    "revenue",
    "gross_profit",
    "margin",
    "promo_cost",
    "incremental_profit",
    "cannibalised_profit",
    "halo_profit",
    "clearance_value",
    "value",
)


@dataclass(frozen=True)
class ComparisonContext:
    """What a comparison reads: a candidate set and the facts it was generated from."""

    options: PromoOptions
    relations: RelationLookup
    """The detected complements, for BUNDLE partners and their basket lift."""
    products: pd.DataFrame
    """sku_id and base_price of every SKU, in scope or not."""

    @cached_property
    def _rows(self) -> dict[tuple[str, Region], list[int]]:
        rows: defaultdict[tuple[str, Region], list[int]] = defaultdict(list)
        for n, line in enumerate(self.options.lines):
            rows[line.sku_id, line.region].append(n)
        return dict(rows)

    @cached_property
    def _base_prices(self) -> dict[str, float]:
        products = self.products
        return dict(
            zip(products["sku_id"].astype(str), map(float, products["base_price"]), strict=True)
        )


def compare(
    sku_id: str, region: Region, context: ComparisonContext, *, chosen: PlanLine | None = None
) -> tuple[MechanismOutcome, ...]:
    """Each mechanism's best option for the SKU in the region, highest value first, then the
    mechanisms with no option; empty when the SKU and region have no options at all.

    `chosen`, a plan line among the options, stands for its own mechanism instead of that
    mechanism's best option. It is a ValueError for it to be for another SKU or region, or
    not among the options.
    """
    options = context.options
    rows = context._rows.get((sku_id, region), [])
    chosen_row = _chosen_row(sku_id, region, options.lines, rows, chosen)
    lifts = _lifts(context.relations, sku_id)
    values = options.table["value"].to_numpy(dtype=float)
    per_mechanism: defaultdict[Mechanism, list[int]] = defaultdict(list)
    for n in rows:
        line = options.lines[n]
        # BUNDLE only with a detected complement as the partner (F-02 AC2).
        if line.bundle_partner_sku_id is None or line.bundle_partner_sku_id in lifts:
            per_mechanism[line.mechanism].append(n)

    available: list[tuple[float, MechanismOutcome]] = []
    unavailable: list[MechanismOutcome] = []
    for mechanism in Mechanism:
        if mechanism is Mechanism.BUNDLE and not lifts:
            continue
        if chosen_row is not None and options.lines[chosen_row].mechanism is mechanism:
            available.append((values[chosen_row], _outcome(context, chosen_row, lifts, True)))
            continue
        candidates = per_mechanism[mechanism]
        if candidates:
            best = candidates[int(np.argmax(values[candidates]))]
            available.append((values[best], _outcome(context, best, lifts, False)))
            continue
        # A duplicate charm price is never the cause: a shallower depth offered that price.
        reasons = options.pruned_by_mechanism.get((sku_id, region, mechanism), frozenset()) - {
            PruneReason.DUPLICATE_PRICE
        }
        if reasons:
            unavailable.append(
                MechanismOutcome(
                    mechanism=mechanism,
                    best=None,
                    unavailable=tuple(reason for reason in PruneReason if reason in reasons),
                )
            )
    # Highest value first; a stable sort keeps ties in mechanism order.
    available.sort(key=lambda ranked: -ranked[0])
    return (*(outcome for _, outcome in available), *unavailable)


def _chosen_row(
    sku_id: str,
    region: Region,
    lines: Sequence[PlanLine],
    rows: Sequence[int],
    chosen: PlanLine | None,
) -> int | None:
    if chosen is None:
        return None
    if (chosen.sku_id, chosen.region) != (sku_id, region):
        raise ValueError(
            f"the chosen plan line is for {chosen.sku_id} in {chosen.region}, "
            f"not the SKU and region compared ({sku_id} in {region})"
        )
    for n in rows:
        if lines[n] == chosen:
            return n
    raise ValueError("the chosen plan line is not among the candidate set's options")


def _lifts(relations: RelationLookup, sku_id: str) -> dict[str, float]:
    """The basket lift of each detected complement of the SKU."""
    complements = relations.complements(sku_id)
    return dict(
        zip(complements["sku_id"].astype(str), map(float, complements["lift"]), strict=True)
    )


def _outcome(
    context: ComparisonContext, row: int, lifts: dict[str, float], chosen: bool
) -> MechanismOutcome:
    line = context.options.lines[row]
    numbers = context.options.table.iloc[row]
    prices = context._base_prices
    partner = line.bundle_partner_sku_id
    return MechanismOutcome(
        mechanism=line.mechanism,
        chosen=chosen,
        best=MechanismOption(
            option=line,
            anchor_sku_id=line.sku_id,
            partner_sku_id=partner,
            basket_lift=None if partner is None else lifts.get(partner),
            effective_price=effective_unit_price(
                line.mechanism, prices[line.sku_id], line.depth_pct
            ),
            partner_effective_price=None
            if partner is None
            else effective_unit_price(line.mechanism, prices[partner], line.depth_pct),
            **{name: float(numbers[name]) for name in _NUMBERS},
        ),
    )
