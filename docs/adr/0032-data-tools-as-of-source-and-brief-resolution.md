# Data tools read at a bound as-of week, pool stock per region, and a deterministic resolver scores brief phrases

E8 (#83) adds three SPEC §9.6 tools, `get_scope_data`, `get_inventory_status` and `get_holidays`, and a resolver that maps brief phrases to catalogue entities. The spec and ticket leave several things open: where the tools get the as-of week, how a region's days of cover and overstock flag are pooled, what "Diwali" means as a promo window, and the resolver's shape, score and ambiguity rule. We chose these with the owner:

- **The as-of week is bound when a data tool is built, as an async source, and awaited on every call.**
  - `AsOfWeekSource` (`promopilot.agents.tools.as_of`) is just `Callable[[], Awaitable[int]]`.
  - The API binds `RetailData.default_as_of_week`, so newly loaded data moves the clock without a restart.
  - A planning session or eval scenario binds a fixed week with `fixed_as_of_week(week)`.
  - The LLM never passes an as-of week, so it cannot read the future.
  - With no data loaded, the call returns a new error code, `data_unavailable`.
  - **This is the shared convention for every data tool**, including `get_competitor_gaps` (#32).
  - We rejected an `as_of_week` input field, which would let the LLM move the clock, and the demand model's as-of week, which ties data reads to the model.
- **Holidays are the one future a tool may show.**
  - The calendar is known in advance, as `RetailData.calendar` already says.
  - `get_holidays` still requires its window to start after the as-of week, where planning happens, and to end within the calendar.
  - Sales, inventory and competitor prices stay strictly before the as-of week (ADR 0008).
- **`get_holidays` returns one row per holiday × region × week.**
  - Each row has the week's start date and the calendar's intensity: the festival week at full strength, the week before at the lead-in share (ADR 0016).
  - A holiday is **national** when the calendar has it in every region.
- **`get_inventory_status` pools a region's stores from the snapshot at the end of the week before the as-of week (ADR 0004).**
  - Available stock is Σ (on hand − safety stock).
  - Days of cover is Σ on hand ÷ Σ each store's daily demand. A store's daily demand is its on hand ÷ its days of cover in the snapshot. A store with nothing on hand adds no demand.
  - The SKU is overstocked in the region when that cover exceeds the company-policy threshold × 7 days.
  - We rejected dividing by recent sales, which would not match the snapshot. We also rejected "any store flagged", which ignores how much stock the region holds.
- **The resolver is a plain deterministic class, `promopilot.agents.resolution.BriefResolver`, not a tool.**
  - The Context agent calls it after its LLM lifts the phrases out of the brief.
  - Its methods are `categories`, `regions`, `products` and `promo_window`. Each returns a `Resolution` with candidates, best first (value, label, score), and an `ambiguous` flag.
  - A product candidate is the set of SKUs that match every named attribute kind (category, subcategory, brand, pack size). Names of one kind are alternatives.
  - "400g namkeen packs" is therefore every SKU that is both Namkeen and 400g.
- **Scores run from 0 to 1.**
  - A phrase is cut into meaningful words: lower case, plurals and filler words ("packs", "products", "and") dropped, "400 g" joined to "400g".
  - A candidate's score is the mean, over every phrase word and every word of its terms, of that word's best difflib similarity on the other side.
  - Similarities below 0.6 count as 0. Words with digits (pack sizes) match only exactly.
  - So the score is exactly 1.0 when every phrase word names a term and every term word is named. A misspelling ("namkin") or a partial name ("care" for Personal Care) scores lower.
  - An exact word match is contested only by another exact match.
- **A resolution is ambiguous when the best score is below 0.7 (the AG-02 threshold) or the runner-up is within 0.1 of it.** No candidate at all is also ambiguous.
- **"Diwali" as a promo window means every week the calendar labels Diwali in the scope regions, first occurrence after the as-of week.**
  - At the default as-of week this is weeks 108–109: the lead-in week and the festival week.
  - Weeks at or before the as-of week are dropped. A holiday not in those regions after the as-of week is no candidate.
  - We rejected the festival week alone, and the festival plus a fixed run-up, because the calendar already encodes pre-festival shopping.

## Consequences

- A promo window read from a festival name is two weeks long, so its plan lines last at most 2 weeks unless the brief or an amendment widens it.
- Every data tool (this ticket, #32 and later E5–E8 tools) takes an `AsOfWeekSource` and reports `data_unavailable` when no data is loaded.
- The Context agent (#46) can use a candidate's score directly as an assumption's confidence, and ask a clarification when a resolution is ambiguous.
- difflib is in the standard library, so no fuzzy-matching dependency is added.
