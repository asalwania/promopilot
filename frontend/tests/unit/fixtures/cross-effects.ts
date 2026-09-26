import type { CrossEffect } from "@/components/cross-effect-callouts";

// One plan line's effects on the other SKUs in its region, as the relations calculators
// return them (ADR 0033): negative units and profit are cannibalisation, positive are halo.
export const crossEffects: CrossEffect[] = [
  { sku_id: "SKU0007", units_change_pct: -12.4, profit_change: -4520.6 },
  { sku_id: "SKU0005", units_change_pct: -3.2, profit_change: -9800 },
  { sku_id: "SKU0002", units_change_pct: -6.51, profit_change: -1200 },
  { sku_id: "SKU0009", units_change_pct: -1.0, profit_change: -300 },
  { sku_id: "SKU0004", units_change_pct: -0.6, profit_change: -15000 },
  { sku_id: "SKU0031", units_change_pct: 8.2, profit_change: 2150 },
  { sku_id: "SKU0040", units_change_pct: 0.4, profit_change: 90 },
];
