import type { Assumption } from "@/lib/api/sessions";

// Every assumption scores at least 0.7: below that the Context agent asks instead
// (AG-02, ADR 0048), and a reading by rules scores exactly 0.7 (ADR 0053). So the
// panel calls anything short of a near-exact reading low (ADR 0061).
export const LOW_CONFIDENCE_BELOW = 0.9;

export function isLowConfidence(assumption: Assumption): boolean {
  return assumption.confidence < LOW_CONFIDENCE_BELOW;
}

export function needsAttention(assumption: Assumption): boolean {
  return assumption.flagged || isLowConfidence(assumption);
}

// The planning-request fields and facts the Context agent lists (ADR 0048 D3), and
// what its questions and amendments are about.
const FIELD_LABELS: Record<string, string> = {
  as_of_week: "As-of week",
  "scope.regions": "Regions",
  "scope.categories": "Categories",
  "scope.sku_ids": "SKUs",
  promo_window: "Promo window",
  marketing_budget: "Marketing budget",
  min_margin: "Minimum margin",
  kvi_price_tolerance: "KVI price tolerance",
  max_promoted_skus_per_category_per_region:
    "Promoted SKUs per category and region",
  regional_budget_caps: "Regional budget caps",
  clearance_targets: "Clearance targets",
  objective: "Objective",
  target_segment: "Target segment",
  overstocked_skus: "Overstocked SKUs",
  undercut_kvis: "Undercut KVIs",
  amendment: "Amendment",
};

// A field the UI does not know yet shows by its own name.
export function fieldLabel(field: string): string {
  return FIELD_LABELS[field] ?? field;
}
