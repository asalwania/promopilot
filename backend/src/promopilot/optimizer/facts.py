"""The plan facts of selected promo options: the plan-time numbers `validate_plan` reads
(ADR 0028, ADR 0046)."""

from collections.abc import Sequence

from promopilot.guardrails import ClearanceFacts, LineFacts, PlanFacts
from promopilot.optimizer.options import PromoOptions
from promopilot.optimizer.solver import OptionFacts


def plan_facts(options: PromoOptions, rows: Sequence[int], facts: OptionFacts) -> PlanFacts:
    """The options at `rows` as plan validation reads them: each line with its option's own
    numbers and its SKUs' facts, and each clearance target's expected units over the promo
    window (its baseline plus the window uplift of every line that sells the SKU there), and
    the relations model's detected substitute pairs among the plan's SKUs (ADR 0075)."""
    table = options.table
    lines = []
    for row in rows:
        line = options.lines[row]
        partner = line.bundle_partner_sku_id
        lines.append(
            LineFacts(
                line=line,
                anchor=facts.sku(line.sku_id, line.region),
                partner=None if partner is None else facts.sku(partner, line.region),
                expected_units=float(table["units"].iloc[row]),
                p90_units=float(table["p90_units"].iloc[row]),
                available_stock=float(table["available_stock"].iloc[row]),
                expected_revenue=float(table["revenue"].iloc[row]),
                expected_gross_profit=float(table["gross_profit"].iloc[row]),
                promo_cost=float(table["promo_cost"].iloc[row]),
            )
        )
    clearance = []
    for target in options.clearance:
        sold = target.baseline_units
        for row in rows:
            line = options.lines[row]
            if line.region is not target.region:
                continue
            if line.sku_id == target.sku_id:
                sold += float(table["window_uplift"].iloc[row])
            if line.bundle_partner_sku_id == target.sku_id:
                sold += float(table["partner_window_uplift"].iloc[row])
        clearance.append(
            ClearanceFacts(
                sku_id=target.sku_id,
                region=target.region,
                available_stock=target.available_stock,
                expected_units=sold,
            )
        )
    sku_ids = sorted({sku_id for fact in lines for sku_id in fact.line.skus})
    return PlanFacts(
        lines=tuple(lines),
        clearance=tuple(clearance),
        substitutes=tuple(facts.substitutes(sku_ids)) if sku_ids else (),
    )
