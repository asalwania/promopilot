import type { ModelEntry } from "@/lib/api/models";

const demandMetrics = {
  baseline_wape: 0.4412,
  baseline_wape_store_sku: 0.2507,
  baseline_wape_region_sku: 0.1409,
  response_skus_fitted: 118,
  elasticity_median_std_error: 0.08734,
};

export const demandV2: ModelEntry = {
  model_id: "8f0f1f4e-2d8b-4b0a-9a57-1c6f3f1d0a02",
  kind: "demand",
  version: 2,
  trained_at: "2026-09-26T06:30:00Z",
  as_of_week: 105,
  metrics: demandMetrics,
  live: true,
};

export const demandV1: ModelEntry = {
  model_id: "8f0f1f4e-2d8b-4b0a-9a57-1c6f3f1d0a01",
  kind: "demand",
  version: 1,
  trained_at: "2026-09-25T06:30:00Z",
  as_of_week: 105,
  metrics: { baseline_wape: 0.45 },
  live: false,
};

export const demandV3: ModelEntry = {
  ...demandV2,
  model_id: "8f0f1f4e-2d8b-4b0a-9a57-1c6f3f1d0a03",
  version: 3,
  trained_at: "2026-09-26T07:00:00Z",
};

// A kind the generated types don't list yet (E5 adds relations) still renders.
export const relationsV1: ModelEntry = {
  model_id: "8f0f1f4e-2d8b-4b0a-9a57-1c6f3f1d0b01",
  kind: "relations",
  version: 1,
  trained_at: "2026-09-26T06:40:00Z",
  as_of_week: 105,
  metrics: { substitute_pairs: 42 },
  live: true,
};
