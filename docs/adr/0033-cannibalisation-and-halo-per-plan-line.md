# Cannibalisation and halo per plan line use the oracle's method on fitted inputs, with a pairwise correction for promoted substitutes

E5 (#31) turns the relations model (ADR 0029) into numbers and callouts. SPEC §9.2 says effect calculators return cannibalised and halo profit per affected SKU in the same region, including out-of-scope SKUs (ADR 0005), and expose pairwise cannibalisation for the optimiser's `y_ij` terms. It does not say how the effect is computed from θ, what the pairwise term is, how relations are served, or how callouts read. We chose these with the owner:

- **One line's effect follows the oracle's per-line method (ADR 0017), on fitted inputs.** A line's price cut moves every detected substitute and complement B of its SKUs (a BUNDLE's partner included) that has an estimated θ, in the line's region only, over the promo weeks and the targeted segments:
  - Δunits = B's baseline × (exp(Σ θ · log(p_eff / base price)) − 1). The sum runs over the line's SKUs. The baseline is `DemandModel.baseline`, and p_eff comes from `promopilot.economics`.
  - Δprofit = Δunits × (B's base price − unit cost).
  - A fall in profit is cannibalisation and a rise is halo, as the oracle counts them. Units moved only by a cross effect are not stock-capped. The line's own SKUs are never counted.
  - `units_change_pct` is Δunits as a share of B's regional baseline over the promo weeks, across every segment.
  - A complement kept by lift alone (θ not estimable) has no number and is left out.
  - We rejected using every estimated θ, including pairs that are not detected, because that would report noise as cannibalisation (SPEC F-04). We also rejected adding a standard deviation now; the E7 simulator samples θ.
- **`pairwise_cannibalisation(line_i, line_j)` corrects the single-line figures for two lines promoted together.** Single-line figures assume every other SKU is at base price. The pairwise term is their sum minus the joint effect, over the weeks and segments both lines price:
  - Each line's own SKUs lose (exp(c) − 1) of their promoted units at their promoted margin. The other line's single-line figure charged baseline units at base margin.
  - A SKU both lines move is moved by both at once, not by each separately.

  The term is 0 across regions, with no common week or segment, or when no SKU of one line is a detected substitute of a SKU of the other. It can be negative. The optimiser subtracts it once per selected pair (SPEC §9.4). It reads a line's own units per week, SKU and segment from a new `DemandModel.line_paths`, which breaks `predict` down and sums back to it.
  - We rejected a constant per SKU pair, which ignores depth, overlap and segment. We also rejected ignoring the interaction, which double-counts a SKU both lines cut.
- **The calculators are library functions** (`line_effects`, `pairwise_cannibalisation` in `promopilot.models.relations`), for candidate generation and the optimiser (#33, #34). `estimate_demand` is unchanged, and no planner tool computes effects yet. The functions take the relations and the demand model through small protocols, so the tests pin every input by hand.
- **`get_relations` takes 1 to 50 `sku_ids`.** For each SKU it returns:
  - substitutes: `{sku_id, theta, std_error, q_value}`, strongest first;
  - complements: `{sku_id, lift, support, theta, std_error}`, highest lift first, with θ and its standard error null where not estimable.

  The output names the relations model's id, version and as-of week. An unknown SKU is `invalid_input`. The tool takes no as-of week (ADR 0032): the relations model carries its own. `GET /api/relations/{sku_id}` answers from the same lookup, in the same shape for one SKU. It returns `404` for an unknown SKU and `503` when no relations model is served.
- **The API serves the latest relations model only on the live demand model.** It is resolved on every call, like demand (ADR 0025). If its `demand_version` is not the live demand version, tools answer `model_unavailable` and the endpoint answers `503`. Retrain puts both new versions live, and `GET /api/models` marks the live relations version. We rejected serving the latest relations with only a warning, because its θ were fitted against another baseline.
- **Callouts.** Cannibalisation reads "Promoting A reduces B's units by N% (−₹X profit)". Halo reads "Promoting A lifts B's units by N% (+₹X profit)". Only |N| ≥ 1% is shown, the top 3 by profit are listed, and the rest are counted as "+k more". The components are presentational and built against fixtures. E10 wires them into the session page.

## Consequences

- Per-line cannibalisation and halo, like the oracle's per-line figures, need not add up to a plan's totals when lines interact. The pairwise terms carry the interaction between substitutes. Two lines that share only a complement are not corrected.
- A line's effect uses `DemandModel.baseline` (the last known competitor index). The line's own numbers use `predict`'s reference-index baseline (ADR 0024), so the two can differ slightly.
- After a failed relations registration (ADR 0029), relations stay unavailable until the next training run registers a matching pair.
