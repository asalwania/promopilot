# The oracle totals a plan jointly, attributes effects one line at a time, and caps only promoted SKUs

ADR 0011 fixed that the oracle scores expected outcomes capped at available stock. Two details were open and were confirmed with the owner in E2.

**Totals and attribution.** A plan's totals (incremental profit, cannibalisation, halo, promo cost, clearance value) come from evaluating all of a region's plan lines together under the true demand function, so interactions between lines (two substitutes promoted at once) are counted once and correctly. Per-line figures attribute effects one line at a time: that line alone against the no-promotion baseline. Per-line cannibalisation and halo therefore need not add up to the plan totals when lines interact; the totals are authoritative. We rejected reporting plan totals only, because F-04/F-05 show cannibalisation and halo per plan line and E9 needs an oracle figure to compare them with.

**Stock cap.** For each plan line, the expected units of its SKU (and of a BUNDLE's partner) over the line's weeks are capped at the pooled available stock of the region (ADR 0004). The baseline is capped the same way over the same weeks, so a SKU that would sell out anyway is not credited with lost sales. SKUs moved only by cross effects (cannibalised substitutes, halo complements) and the pull-forward weeks after a promotion are not capped: restocking is assumed there.

## Consequences

- The oracle evaluates each affected region over the plan's weeks plus the pull-forward window (4 weeks) after the last line ends, for every SKU in the region, in scope or not (ADR 0005).
- Promotions before the as-of week are ignored in both the plan and the baseline scenario; their pull-forward affects both equally.
- A SKU is overstocked for clearance value when its pooled days of cover in the region exceed the company-policy threshold.
- `units`, `baseline_units` and `sell_through` of a plan line refer to its anchor SKU; revenue, gross profit, promo cost and incremental profit include a BUNDLE's partner.
