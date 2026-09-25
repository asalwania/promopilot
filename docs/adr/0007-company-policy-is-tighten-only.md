# Company policy is tighten-only; minimum margin is plan-level with a below-cost floor

The parent company's standing rules live in **company policy** (config), separate from the brief. A brief may tighten policy but never loosen it: an attempt to loosen it (e.g. "margin 12%" against a 15% margin floor) keeps the policy value and is flagged to the user. When a planning request is infeasible, the proposed **relaxation** only touches the brief's constraints (marketing budget, minimum margin down to the margin floor, clearance target, scope); company policy is never relaxed, and if policy itself is binding the agent says so.

**Minimum margin** is enforced at plan level: the blended expected margin of all plan lines must reach it. Individually, a plan line may not sell below unit cost unless its SKU is overstocked. This deliberately deviates from SPEC §9.3's per-option minimum-margin pruning, which would make deep clearance discounts impossible and contradicts the clearance requirement (F-06 AC2).

## Default company policy (tunable in config)

| Rule | Default |
|---|---|
| Margin floor | 15% |
| Maximum discount | 50% |
| Undercut threshold (KVI) | 5% (CPI < 0.95) |
| KVI price tolerance | ±2%, off unless the brief enables it |
| Overstock threshold | days of cover > 8 weeks |
| Write-off rate | 30% of unit cost |
| Fixed marketing cost per plan line per week | PCT_OFF ₹2,000 · FIXED_PRICE ₹2,000 · BOGO ₹3,000 · BUNDLE ₹4,000 |
| Max promoted SKUs per category per region | 10 |
