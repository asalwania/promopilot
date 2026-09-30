# Demand prediction computes each store-invariant term once, and every number is unchanged bit for bit

#113: on the seed-42 demo brief (Snacks and Beverages, North and West, weeks 108–109, ₹2 lakh, as of week 104), `generate_options` took about 8 s on a quiet machine. Almost all of it was `DemandModel.predict`. The acceptance criteria are under 4 s on a laptop, with an equivalence test against the current predictions. We chose these with the owner at #113's decision gate (D1–D8; every recommended option).

## What the profile found

The profile used the seed-42 world fitted as `make train` fits it, with no LLM and no database. The machine was loaded by other agents, so the figures are medians of 5 runs and their shares matter more than their size.

- `generate_options`: 16.6 s. Of that:
  - `predict`: 12.4 s (75%). Most of it went to building the rows with pandas merges on string columns (4.8 s), two `log_effect` passes (3.5 s) and three `variance` passes (about 3 s).
  - `line_effect_totals`: 2.3 s, about half of it two regional baseline forecasts.
  - Enumeration, stock pruning, clearance and the rest: about 1.9 s.
- `predict` built 2,225,600 store × segment × week rows for the 17,625 options it predicted. Behind them were only 12,296 distinct promo-response rows and 15,360 distinct baseline rows:
  - a row's promo response (price, mechanism, pull-forward share, competitor terms) does not depend on the store;
  - an option's target-segment variants share every row but the targeted segment's (ADR 0077's D10).
- `Relations` already indexes each SKU's partners on its first lookup (#73, ADR 0077's D1). Relation lookups no longer show in the profile.

## Decisions

- **D1–D3. One array pipeline serves `predict`, `line_paths` and `response_rows`.** `_Response._grid` builds every row as arrays of codes: option, SKU (the anchor, then a BUNDLE's partner), week, store and segment, in exactly the order the old merges listed them.
  - Each row points to a *cell*: its option, SKU, week and segment. The price, mechanism, pull-forward share, competitor terms, `log_effect`, its `exp` and the `design` covariates are computed once per cell, and each row reads its cell's.
  - The baseline is forecast once per store × SKU × segment week at the series' reference competitor index, as before, without the 2.2 million-row de-duplication.
  - Every total adds the rows in the same order as before:
    - `predict`'s totals use `np.bincount`;
    - `PromoResponse.variance` now takes each row's SKU (a categorical), its covariates, its mean and its group. It sums the gradient term by term with `np.bincount`, which adds in the same order as the old `np.add.at`. It keys each (group, SKU) pair as one integer, which sorts as the old two-column `np.unique` did.
  - `line_paths` still groups with pandas, on integer codes that sort as the names do, so its Kahan sums and their order are unchanged.
- **D2. Bit for bit, not within a tolerance.** Every number in `predict`, `line_paths` and `response_rows` equals the old pipeline's exactly. The ticket allowed 1 paisa and 1e-9 units; exact equality is what guarantees that no option, plan, simulation or recorded session changes.
- **D1. The test oracle is a frozen copy.** `tests/unit/models/reference_demand.py` is the pre-#113 pipeline, copied verbatim. A frozen copy is exact on every platform, where golden files could differ between Windows and CI's Linux (LightGBM, numpy SIMD).
- **D4. `_Features.build` is unchanged.** It was to be sped up only if the demo stayed above about 3 s on a quiet machine. It does not.
- **D5.** Nothing more for `Relations._partners`: #73 did it.
- **D6.** A `model`-marker test times `generate_options` on the demo brief, twice, and asserts the faster run is under 4 s.
- **D8. Rejected: summing each series' store baselines before applying the response.** It would be faster still, but it changes the order of the sums, so the last bits of some numbers could move. A paisa that rounds differently could change a recorded session.

## Consequences

- **Measured on the demo brief**, medians on the same loaded machine, alternating the old and new code:
  - `generate_options`: 16.6 s → about 4.2 s;
  - `predict`: 12.4 s → about 2.2 s.
  - What is left is `line_effect_totals` (about 1.4 s), three baseline feature builds (about 1.1 s in all) and enumeration.
  - On a quiet machine this is roughly 2 s, from about 8 s.
- **`line_paths` is faster too.** The optimiser's pairwise pricing and the clearance window uplifts read it.
- **No cassette changes.** Every number is bit-identical, so the candidate set, the pairwise terms, the plan, the simulation and the Explainer's data are the same. The offline replays, `make check-cassettes` and `make eval-smoke`, report no misses.
- **Tests:**
  - on the fitted small world, `predict`, `line_paths` and `response_rows` equal the frozen copy exactly:
    - every mechanism and target segment, including a BUNDLE;
    - durations of 1–4 weeks;
    - a start at the as-of week, and a pull-forward cut short by the calendar;
    - competitor-price overrides;
    - a repeated line, one line, and a shuffled batch;
  - every option the model cannot predict raises the same `ValueError` as before;
  - on the demo brief (`model` marker), the candidate table equals the one generated with the frozen copy, bit for bit, and generation takes under 4 s.
- **The row-building helper `_as_promotions` is gone.** The model fit still builds its history rows with the pandas helpers (`_exposure`, `_priced`, `_with_ratios`).
- There is no migration, no new configuration and no API change.
