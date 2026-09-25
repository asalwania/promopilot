# Region-level plan lines with pooled regional stock

A plan line is a (SKU, region) decision that runs in all five stores of the region, and its stock constraint uses **available stock** pooled across those stores: Σ stores (on_hand − safety_stock), with P90 predicted units required to fit inside it. Stock, sales and segment mix are recorded per store, so a store-level plan (or a per-store stock check) was the obvious alternative; we chose regional pooling because promotions are planned, shown and compared per region (SPEC F-07), it keeps the optimiser at one variable set per region instead of five, and it assumes, as most multi-store retailers can, that stock can be rebalanced between stores in a region.

## Consequences

- The simulator still reports a **per-store stock-out probability** for each plan line as a risk signal; it is not a hard constraint.
- Demand predictions are made per store and summed to the region for the optimiser.
- If store-level execution is ever needed, this is the decision to revisit (the data already supports it).
