# The baseline trains on clean weeks with horizon-safe features, and the registry pickles artifacts to a volume the api loads from

E4 (#26) adds the first trained model and the model registry. SPEC §9.1 lists the baseline's features and asks for a 12-week holdout WAPE. SPEC §8.2 and SF-02 define the registry row. The spec does not say which rows the baseline learns from, how features behave in future weeks, where artifacts live in Docker, or what `/health` reports. We chose these with the owner:

- **Clean weeks only.** The baseline learns from a store × SKU × segment × week row only if that SKU was not promoted to that segment, directly or as a bundle partner, in that week or the 4 weeks before (the pull-forward window, ADR 0016). Promo uplift and the post-promo dip belong to the promo response model (#27), not the baseline. We rejected training on every row with a promo flag, which mixes the two stages.
- **Horizon-safe features.** The features are:
  - a series level (the mean clean units of the store × SKU × segment over the fit window);
  - `lag_52` (clean units 52 weeks earlier; missing when unavailable);
  - week-of-year sine and cosine;
  - holiday name and intensity for that week, plus the next week's intensity;
  - region, category, subcategory, base price and KVI flag;
  - segment;
  - the competitor price index, where future weeks carry the last index known before the as-of week (future competitor prices are hidden, ADR 0016).

  Every feature is known for any week up to 52 weeks past the as-of week, so the model forecasts a promo window without recursion. We rejected short autoregressive lags, which need recursive forecasting and invite leakage. The model is LightGBM with a Poisson objective, fixed hyperparameters, `deterministic=True` and an explicit seed.
- **Validate, then refit.** A model fitted on history before `as_of − 12` is scored on the clean rows of the last 12 weeks. The registered model is then refit on all history before the as-of week with the same seed.
- **WAPE at three grains.** The model's grain is store × SKU × segment × week. At that grain the counts average about 4 units, so noise dominates: Poisson noise alone gives WAPE ≈ 0.34 with perfect means. The metrics therefore report WAPE at three grains:
  - `baseline_wape` (the model grain);
  - `baseline_wape_store_sku` (summed over segments);
  - `baseline_wape_region_sku` (summed over the region's stores, the grain plan lines use, ADR 0004).

  On the seed-42 world they are 0.44, 0.25 and 0.14. A naive series-mean forecast scores 0.45 and 0.27 at the first two grains.
- **Pickled artifacts under `MODEL_DIR`, relative paths in the row.**
  - `ModelRegistry.register` gives each kind its next version.
  - The artifact is written to `MODEL_DIR/<kind>-v<N>.pkl` inside the insert's transaction, so a failed write leaves no row.
  - The row stores the path relative to `MODEL_DIR`. The same row therefore resolves natively (`../models`, gitignored) and in Docker (`/app/models`).
  - Only the registry writes these pickles, and only it loads them.
- **Docker trains inside the api container.** Compose mounts a named volume `model-artifacts` at `/app/models`. The stack's model is trained with `docker compose exec api python -m promopilot.models`, as ADR 0022 does for data, and CI does this after loading the world. We rejected a bind mount of `./models`, which breaks on Linux CI when the runner's uid differs from the image's `app` user. A model trained natively with `make train` is registered in the same Postgres, but its artifact is not on the volume, so the stack reports it `missing`.
- **`/health` loads the latest model and retries while it is missing.** The API loads the latest demand model at startup. While none is loaded, each `/health` call tries again, so a model trained after `make up` is picked up without a restart. `checks.model_registry` is `ok` or `missing`. A missing model makes `status` `degraded`, because from E6 on the planner cannot estimate demand without one. The endpoint still returns HTTP 200 (ADR 0001).

## Consequences

- The model is the region-level baseline's source for E4–E7. #27 adds `DemandModel.predict` beside `baseline`, and #29's retrain reuses `train_demand_model` and must swap the loaded model explicitly.
- A fresh stack is `degraded` until `make data` and a training run. The quick start and CI train after loading data.
- Changing the model's class layout invalidates old pickles. Retrain after upgrading.
