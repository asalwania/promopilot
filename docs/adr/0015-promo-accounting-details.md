# Promo accounting details: charm prices, fixed cost in profit, money as float rupees

ADR 0005 fixed the promo economics but left three details open; these are the choices `promopilot.economics` implements (confirmed with the owner, E2).

- **Charm price.** A FIXED_PRICE line sells at the largest whole-rupee price ending in 9 at or below the depth price (₹110 at 10% → ₹99; ₹100 at 10% → ₹89). On cheap SKUs this can be noticeably deeper than the depth level; the economics always use the effective price, and candidate generation (E6) prunes FIXED_PRICE options whose effective discount exceeds the company-policy maximum. We rejected dropping FIXED_PRICE when the charm price lands more than a few points below the depth, and paise-level charm prices (₹26.9), which are rare in Indian retail.
- **Fixed marketing cost reduces profit.** Incremental profit is gross profit over baseline (promo weeks plus pull-forward weeks) **minus the line's fixed marketing cost**. The fixed cost also counts toward the marketing budget as part of promo cost. Discount funding is not subtracted again, because the lower price already carries it. We rejected counting fixed cost only against the budget, which would let the optimiser spend budget on lines whose gain does not cover their cost.
- **Money is float rupees.** Economics functions take and return rupees as floats and work elementwise on numpy arrays, so the vectorised simulator shares the same definitions. Only the CP-SAT optimiser converts to integer paise, as its solver requires. We rejected Decimal or integer paise everywhere, which would be exact but slow and awkward inside Monte Carlo.

## Consequences

- The objective in SPEC §9.4 (`incremental_profit_o + halo_o + clearance_value_o`) is net of each option's fixed marketing cost.
- A BUNDLE's discount funding is the sum of both SKUs' funding; its fixed cost is charged once per line-week.
