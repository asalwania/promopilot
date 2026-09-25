# Promo economics are shared definitions; the oracle scores expected outcomes, capped at stock

The definitions in ADR 0005 (a mechanism's effective unit price, promo cost, clearance value, margin, incremental profit) are implemented once, as pure functions in `promopilot.economics`, and used by the optimiser, simulator and oracle alike. The alternative was an oracle with its own independent economics, which could catch a bug in the planner's arithmetic; we chose sharing because these are definitions, not estimates, and two implementations drifting apart would make regret and "beats the baseline" measure a disagreement about accounting rather than plan quality. What the oracle keeps independent is the thing that matters: it uses the **true** demand parameters from ground truth, while the planner uses fitted ones.

The oracle scores a promo plan by its **expected** outcome under the true demand function (no sampling), so a plan always gets the same score and regret is stable; demand noise belongs to the simulator. Expected units sold are **capped at available stock** (pooled per region, ADR 0004), as they would be in a real store, and the oracle reports where the cap bit, so a plan that over-promises stock is penalised instead of credited with sales it could not make.

## Consequences

- `promopilot.economics` is tested with hand-computed cases in E2, before any model exists.
- A plan's oracle profit can be lower than its predicted profit purely because of stock-outs; the eval report shows stock-capped lines separately.
