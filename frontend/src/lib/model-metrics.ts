// Registry metric keys the UI knows (ADR 0023, ADR 0024, ADR 0030); any other
// key shows under its raw name to 3 decimals.
type Unit = "share" | "count" | "decimal";

const KNOWN_METRICS: Record<string, { label: string; unit: Unit }> = {
  baseline_wape: { label: "WAPE, store × SKU × segment", unit: "share" },
  baseline_wape_store_sku: { label: "WAPE, store × SKU", unit: "share" },
  baseline_wape_region_sku: { label: "WAPE, region × SKU", unit: "share" },
  response_skus_fitted: { label: "SKUs with a fitted response", unit: "count" },
  elasticity_median_std_error: {
    label: "Median elasticity std. error",
    unit: "decimal",
  },
};

const FORMATS: Record<Unit, Intl.NumberFormat> = {
  share: new Intl.NumberFormat("en-IN", {
    style: "percent",
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  }),
  count: new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }),
  decimal: new Intl.NumberFormat("en-IN", {
    minimumFractionDigits: 3,
    maximumFractionDigits: 3,
  }),
};

export function metricLabel(key: string): string {
  return KNOWN_METRICS[key]?.label ?? key;
}

export function formatMetric(key: string, value: number): string {
  return FORMATS[KNOWN_METRICS[key]?.unit ?? "decimal"].format(value);
}
