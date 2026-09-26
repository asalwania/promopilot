# Relations use one pooled cross effect per pair on the demand model's fit, and basket lift confirmed by it

E5 (#30) adds the relations model (SPEC §9.2). The spec says which rule keeps a substitute (ADR 0013) and that complements come from basket lift confirmed by θ < 0 "where estimable". It does not say how θ is fitted, what estimable means, how support is measured, what the tests hold, or how relations enter the registry. We chose these with the owner:

- **One symmetric θ per unordered pair, from a pooled Poisson GLM.** The rows are region × segment × week unit totals of both SKUs, the grain the promo response is fitted on (ADR 0024). Each row's offset is the demand model's fitted log-mean (baseline times own-promo response). The regressor is the partner's `log(p / p_ref)` in the same region, segment and week, and each SKU has its own intercept. Standard errors are robust (HC0) and the p-value is two-sided. The true θ_ij and θ_ji are drawn separately, but both have the same sign and range (ADR 0016), and pooling halves the noise. In a prototype on the seed-42 world, fitting each direction separately gave substitute precision/recall 0.86/0.91. The pooled fit gave 0.89/1.00.
- **The demand model exposes its in-sample fit.** `DemandModel.fitted_history(history)` returns units, fitted mean and `log_price_ratio` per region × SKU × segment × week before its as-of week. Relations call it rather than refitting a baseline, and never import demand's private helpers. `relations.fit` requires the demand model to share its as-of week, so neither model sees data the other did not.
- **Substitutes.** Every within-subcategory pair whose θ is estimable is tested. BH runs over all of them, and a pair is kept if q < 0.05 and θ ≥ 0.1 (ADR 0013). A pair whose prices never moved is not tested and is not a substitute.
- **Complements.** Support is the share of baskets that hold both SKUs, with a minimum of 0.001. Lift must be above 1.5. θ is estimable when the partner's price moved in the pair's rows and the fit converged with a finite, positive standard error. Among the lift candidates where θ is estimable, a candidate is kept only if θ < 0 with BH q < 0.05, with BH run over those candidates. Where θ is not estimable, lift alone decides. Candidates are not limited to cross-category pairs. On the seed-42 world, lift > 1.5 with no support minimum gave precision 0.35. The θ confirmation raised it to 0.93, and the support minimum raised it to 1.00.
- **Thresholds live in `RelationsConfig`**: `substitute_max_q` 0.05, `substitute_min_theta` 0.1, `complement_min_lift` 1.5, `complement_min_support` 0.001 and `complement_max_q` 0.05. They are code config, not environment variables. Retrain takes no body and fits exactly what `make train` fits (ADR 0026). Each version records its thresholds in the registry.
- **The relations object.** `substitutes(sku)` returns `sku_id, theta, std_error, q_value`, strongest first. `complements(sku)` returns `sku_id, lift, support, theta, std_error`, highest lift first, with NaN θ where it is not estimable. `cross_effect(i, j)` returns θ, its standard error and the raw p-value for any pair the fit estimated, symmetric in i and j, and otherwise None. These are backed by one table keyed by SKU pair, not scipy sparse matrices. The table is as sparse and needs no new direct dependency. The `seed` argument is accepted for a uniform fit signature. The fit draws no random numbers.
- **Tests.** A relations fixture (4 categories × 24 SKUs, 4 regions × 3 stores, 104 weeks, 20,000 baskets, 20 complement pairs, seed 5) runs in `make test` under the `model` marker, in about 25 s. It holds substitute and complement precision ≥ 0.8 and recall ≥ 0.7 against datagen's in-memory truth (ADR 0010). It measured substitutes 0.92/1.00 and complements 1.00/0.90. On the full seed-42 world, it measured substitutes 0.89/1.00 and complements 1.00/1.00. The unit tests cover:
  - exact lift and support on hand-built baskets;
  - the BH and effect-size rule;
  - leakage at the as-of week;
  - determinism.
- **Registry and training.** Relations are model kind `relations`, pickled like demand (ADR 0023). `train_models` fits demand, then relations, and registers each only after both fits succeed. The relations entry's metrics hold:
  - the counts: `substitute_pairs`, `substitute_pairs_tested`, `complement_pairs`, `complement_candidates`, `complement_candidates_estimable` and `baskets`;
  - the five thresholds;
  - `demand_version`, the demand version it was fitted on.

  `make train` and `POST /api/models/retrain` both run it. Retrain's `201` still returns the demand entry, so the API contract does not change. Relations appear in `GET /api/models` with `live: false`, because the API does not load them until #31.

## Consequences

- Training the seed-42 world now takes about 20 s longer: the relations fit takes about 18 s of it.
- A demand version and a relations version are registered back to back but not in one transaction. If the second insert fails, the demand version stays registered with no relations version. The next training run repairs that.
- #31 loads the latest relations for `get_relations` and the effect calculators. It should check that their `demand_version` matches the live demand model.
