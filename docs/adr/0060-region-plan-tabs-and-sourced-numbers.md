# The plan shows in a tab per region plus a side-by-side tab; plan lines keep their uplift, segment uplift and cross effects, and a frontend map names each number's tool

E10 (#60) is where managers review the plan region by region (F-07). #60 asks for:
- a plan table per region: SKU, mechanism, depth, duration, start week, target segment, uplift, P10–P90 profit, stock-out risk and promo cost;
- the same SKU side by side across regions;
- cannibalisation, halo and undercut callouts on the affected lines;
- a mechanism comparison drawer per line, and bundle suggestions;
- the rationales and the plan summary;
- a tooltip naming the source tool on every number (SPEC §11).

The read model lacked some of this. It had no baseline, so no uplift. It had no uplift by segment (F-03 AC2), and it had no per-SKU cannibalisation and halo (ADR 0033), only each mechanism's totals. It named no tools, and it carried no competitor gaps. We chose the following with the owner (D1–D14 on #60, every recommended option).

## Decisions

- **D1. Plan lines keep their uplift, their segment uplift and their cross effects.**
  - `PlanRevisionLine` gains four fields:
    - `baseline_units`: the anchor SKU's no-promotion units over the promo weeks;
    - `uplift_pct`: the line's expected units above that baseline, as a percentage;
    - `segments`: one `SegmentUplift` per segment, in `Segment` order, with its units, baseline and uplift;
    - `cross_effects`: one `LineCrossEffect` per SKU the line moves in its region (`sku_id`, `units_change_pct`, `profit_change`), largest profit change first.
  - The planner computes these when it builds a revision, deterministically:
    - The baseline comes from the options table the line was chosen from.
    - The segments come from `DemandModel.predict` on the chosen lines. This is the same prediction, so they sum to the line's units.
    - The cross effects come from `models.relations.line_effects`. They sum to the chosen option's `cannibalised_profit` and `halo_profit`.
    - The percentages come from the domain function `uplift_pct`. The UI divides nothing.
  - **Migration 0014** adds nullable `plan_lines` columns: `baseline_units`, `uplift_pct`, `segments` (JSONB) and `cross_effects` (JSONB). Lines planned before #60 read back with nulls and empty lists, and the UI shows "—" for them.
  - The type is `LineCrossEffect`, not `CrossEffect`, because the ground-truth boundary test forbids the ground truth's `CrossEffect` name outside `datagen` and `evals`.
  - No LLM request changes. The Explainer's view picks its line fields explicitly (ADR 0050 D3), and `make check-cassettes` replays every recorded session.
- **D2. A frontend provenance map names each number's tool.** This **amends #12's "the read model carries a source tool per numeric field"**. Provenance is fixed per read-model field by the architecture, not per session, so sending it in every response would add no information.
  - `frontend/src/lib/sources.ts` holds the map:
    - the decision (depth, start, duration) comes from `run_optimizer`;
    - a line's own expected numbers and cross effects come from `generate_candidates`;
    - the segment uplift comes from `estimate_demand`;
    - every P10–P90 range and stock-out risk comes from `simulate_plan`;
    - the drawer comes from `compare_mechanisms`;
    - undercuts come from `get_competitor_gaps`.
  - Every number renders through `SourcedNumber`.
- **D3. A tab per region, then "Compare regions".**
  - There is one tab per region of the request, plus any region that has lines, in Region order. Each tab is labelled with its line count.
  - The page opens on the first region with a line. A region with none says "No plan line in East."
  - Each region tab shows the region's simulated stock-out risk.
  - "Compare regions" has one row per SKU, in plan order of its first line, and one column per region with lines. Each cell shows the mechanism, depth, duration, segment and expected incremental profit, or "—".
- **D4. Columns.** SKU, Mechanism (with "+ partner" for a BUNDLE), Depth, Start, Duration, Target segment, Uplift, Profit P10–P90, Stock-out risk, Promo cost, Expected incremental profit, Notes and Details. The Region column is gone, because the tab gives it. Notes are badges (Cannibalisation, Halo, Undercut) for lines with a callout.
- **D5. Profit P10–P90 is the simulator's gross-profit range** for the line. Its tooltip gives the P50, the runs and the seed. The simulator has no incremental-profit percentiles, and adding them is out of scope. Expected incremental profit stays in its own column.
- **D6. Uplift is expected units against the no-promotion baseline over the promo weeks.** The tooltip gives both unit counts. Segment uplift uses the same definition.
- **D7. Money in the plan area follows ADR 0050 D2**, so a table figure reads as the rationale beside it does:
  - whole rupees with Indian grouping below ₹1 lakh;
  - lakh, then crore, to at most two decimals, with trailing zeros dropped.

  This is `formatMoney` in `lib/format.ts`, which mirrors `guardrails.format_rupees`. The tooltip gives the exact rupees. `formatRupees` (ADR 0021) stays for the other pages and tooltips.
- **D8. `SourcedNumber` keeps its native `title` tooltip and now takes keyboard focus** (`tabIndex=0`). The callouts carry the same "Source: …" title on each item.
- **D9. Line details are collapsed behind a "Details" toggle.** Expanded, a line shows:
  - its Explainer rationale (`rationales[i]` belongs to `lines[i]`);
  - an uplift-by-segment table;
  - the Cannibalisation, Halo and Undercut callouts.

  The plan summary sits above the tabs. When the template wrote it, it carries a "Template explanation" badge with the fallback reason.
- **D10. Undercuts come from `GET /api/competitors/gaps?as_of_week=<request>&kvi_only=true`.** This is the same data the planner read (ADR 0031).
  - `useCompetitorGaps` (`lib/competitor-gaps.ts`) is shared with #63's competitor panel through one query key, and is never stale.
  - `SessionView` passes the gaps to `SessionDetails`.
  - While the gaps load, or if they fail, the plan shows without undercut callouts.
- **D11. The mechanism drawer is a shadcn Sheet on the right.**
  - It has a row per mechanism: its best option, units, margin, promo cost, incremental profit and value, with the chosen one badged. An unavailable mechanism lists its reasons.
  - A BUNDLE with a best option opens the drawer with a **bundle suggestion**: the pair, the basket lift and the expected incremental profit (F-05 AC3).
  - A line with no comparison has no drawer button.
- **D12. Lines stay in plan order,** with no sort controls, and show SKU ids only.
- **D13. Tests.**
  - **Vitest:**
    - the plan table: columns, every tooltip, lakh formatting, dashes for old lines, details, segments;
    - the drawer: comparison, bundle suggestion;
    - the region tabs: tabs, switching, empty region, first region with lines, side by side;
    - `formatMoney`;
    - the gaps client;
    - `SessionDetails` and `SessionView`: plan summary, undercuts, a failed gaps read.
  - **Backend:**
    - domain tests;
    - planner tests: segments sum to the units, and cross effects sum to cannibalisation and halo;
    - the sessions API integration test, round-tripping through Postgres.
  - **Playwright:** the composed-stack plan journey also checks the region tabs, a "Source:" tooltip, the details and segment table, the drawer, the West tab and "Compare regions". No planning run is added.
- **D14. These decisions are recorded here,** because #62–#64 build on the plan area.

## Consequences

- New public names:
  - domain: `SegmentUplift`, `LineCrossEffect`, `uplift_pct`;
  - frontend: `RegionPlanTabs`, `PlanTable` (now per region, fed `PlanRow`s), `MechanismDrawer`, `PlanSummary`, `useCompetitorGaps`, `SOURCES`, and `formatMoney`, `formatShare` and `formatUplift`.
- `getCompetitorGaps` takes optional `asOfWeek` and `kviOnly`. The `/data` page calls it as before.
- `SessionDetails` takes an optional `competitorGaps` prop next to #61's `actions`.
- Planning computes one more prediction and one `line_effects` call for the chosen lines, which is well under a second.
- Nothing in the backend reads the new fields. The Explainer and Critic ignore them, so a later ticket may cite segment uplift in rationales only through its own grounded view.
