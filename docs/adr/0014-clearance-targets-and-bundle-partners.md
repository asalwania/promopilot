# Clearance targets apply only to brief-named SKUs; a BUNDLE partner is locked

Two optimiser rules the spec left open.

**Clearance targets.** An **overstocked SKU** is either flagged by days of cover above the company-policy threshold or named in the brief for clearance (CONTEXT.md). Only brief-named SKUs get a **clearance target** (hard, or penalised and reported as a violation when infeasible, per SPEC §9.4). SKUs flagged only by days of cover get no target; they still add **clearance value** to the objective (ADR 0005), so the optimiser clears them when it pays. We rejected a policy-wide default target because it would make many ordinary briefs infeasible over stock the user never asked about.

**BUNDLE partners.** A BUNDLE is one plan line on its anchor SKU. Its partner:

- must be a detected complement of the anchor;
- may sit outside the brief's scope, as halo already does (ADR 0005);
- must have P90 bundle units within its own available stock (ADR 0004);
- cannot have its own plan line in the same region, because the one-line-per-SKU-per-region rule counts the partner.

The bundle's discount is split between the two SKUs pro-rata by base price (ADR 0005). We rejected letting the partner carry its own line, because that double-counts discount and stock, and rejected in-scope-only partners, because they would leave most complement pairs unusable.
