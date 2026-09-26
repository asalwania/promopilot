# Competitor gaps compare the last known competitor price with our base price; the KVI tolerance is one-sided; data tools bind the as-of week

E5 (#32) adds the competitor-gap service (`promopilot.competitors`), the `get_competitor_gaps` tool, `GET /api/competitors/gaps` and an undercut callout. SPEC §5 defines the competitor price index as competitor price ÷ our price, and ADR 0007 sets the undercut threshold (5%) and the KVI price tolerance (±2%, off unless the brief enables it). The spec does not say which of our prices or which competitor price to use, how the gap is signed, how the tool gets its as-of week, what the tool and API return, or what the optimiser's tolerance check looks like. We chose these with the owner:

- **The index uses our base price.**
  - CPI = competitor price ÷ our base price, the same index the demand model uses (ADR 0023, ADR 0024).
  - The gap is 1 − CPI. It is positive when the competitor is cheaper and negative when they are dearer.
  - A KVI is **undercut** when its CPI is strictly below 1 − the undercut threshold, so with the default 5% a 4.9% gap is not undercut, and neither is a gap of exactly 5%, but a 5.1% gap is. A non-KVI is never undercut.
  - We rejected dividing by the last price we actually charged. That price includes our own promotions, so a gap would shrink or vanish just because we were on promo last week.
- **The competitor price is the latest one before the as-of week.**
  - This is the "last known" price `estimate_demand` already assumes (ADR 0024).
  - Each row carries the price's week and whether it was a competitor promo, so the planner and the manager can tell a temporary promo from a standing price.
  - A SKU × region with no price before the as-of week is left out.
  - Prices at or after the as-of week are ignored twice: `RetailData.latest_competitor_prices` filters them in SQL (`DISTINCT ON` region and SKU), and `competitor_gaps` filters any history it is given.
  - We rejected a 4-week average. It would hide a competitor promo that is live right now, which is exactly what a manager needs to react to.
- **One output shape serves the tool and the API.**
  - `CompetitorGaps` holds the as-of week, the undercut threshold and KVI tolerance it was judged by, and every matching row, widest gap first.
  - Each row has the region, SKU, name, category, subcategory, KVI flag, base price, competitor price, competitor promo flag, price week, CPI, gap and undercut flag. The numbers are unrounded.
  - Tool filters: `regions`, `categories`, `sku_ids` and `kvi_only`. If a filter is omitted, it includes everything.
  - API filters: `region`, `category`, `kvi_only` and `as_of_week`.
  - The threshold and tolerance come from company policy, bound when the tool or service is built. The LLM can never set them.
  - An unknown SKU or category is `invalid_input` from the tool and `422` from the API.
- **Data tools bind the as-of week when they are built; the LLM never passes it.**
  - The tool follows the data tools' convention (ADR 0032). `get_competitor_gaps_tool(data, as_of_week, policy=...)` takes an `AsOfWeekSource`, an async source that resolves the as-of week on every call. `build_app` passes `RetailData.default_as_of_week`. A session or an eval can bind a fixed week with `fixed_as_of_week`.
  - The tool input has no `as_of_week` field, and extra fields are rejected, so the LLM cannot move the clock (ADR 0008).
  - Without loaded data the call returns `data_unavailable`.
  - `GET /api/competitors/gaps` is for people, so it keeps an optional `as_of_week` query parameter. By default it uses the data's default as-of week, and it returns `409` when no data is loaded.
- **The KVI tolerance is one-sided.**
  - `CompetitorGaps.within_kvi_tolerance(line)` is the optimiser's check (#36).
  - Each KVI the line promotes passes when its effective unit price under the line's mechanism is at most the competitor price × (1 + tolerance). A BUNDLE promotes both its SKUs. BOGO counts as 50% off, and FIXED_PRICE uses its charm price (ADR 0015).
  - Pricing below the competitor always passes. The rule only stops a KVI promotion that still leaves us visibly dearer than the competitor.
  - Non-KVIs always pass, and so does a SKU with no known competitor price in the gaps it is asked about.
  - The helper does not know whether the brief enabled the rule; the caller applies it only when the planning request does.
  - We rejected reading ADR 0007's "±2%" as a two-sided band. It would forbid deep KVI discounts, and so any response to an undercut that beats the competitor.
- **The undercut callout is presentational.**
  - `UndercutCallout` takes the gap rows and lists each undercut KVI as "Competitor is 5.1% cheaper on X in North (₹94.90 vs ₹100.00)". The gap shows one decimal and prices show paise.
  - A competitor promo price gets an "On promo" badge.
  - It renders nothing when no KVI is undercut.
  - It is built against fixtures and placed on the session page's competitor panel in E10.

## Consequences

- `promopilot.competitors` is a new module over the `data` repositories, `domain` and `economics`. It never reads ground truth.
- #36 builds `CompetitorGaps` for the request's scope and as-of week (with a tightened policy if the brief tightens it) and calls `within_kvi_tolerance` per candidate when the request enables the rule. Its price-match candidates come from the undercut rows.
