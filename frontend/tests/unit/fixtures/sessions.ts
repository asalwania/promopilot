import type { components } from "@/lib/api/schema";

type SessionResponse = components["schemas"]["SessionResponse"];
type PlanRevisionLine = components["schemas"]["PlanRevisionLine"];

export const SESSION_ID = "6f1c2c1e-6a53-4a8e-9d3b-0a4f3f0f7b21";

const BRIEF =
  "Plan a Diwali push for Snacks in North and West, weeks 105 to 108, budget 2 lakh.";

export const planningSession: SessionResponse = {
  session_id: SESSION_ID,
  status: "planning",
  brief: BRIEF,
  planning_request: null,
  plan_revision: null,
  error: null,
};

export const planLines: PlanRevisionLine[] = [
  {
    line: {
      sku_id: "SKU0003",
      region: "North",
      mechanism: "PCT_OFF",
      depth_pct: 20,
      start_week: 105,
      duration_weeks: 4,
      target_segment: "All customers",
      bundle_partner_sku_id: null,
    },
    expected_units: 812.5,
    promo_cost: 13812.5,
    expected_incremental_profit: -13812.5,
  },
  {
    line: {
      sku_id: "SKU0011",
      region: "West",
      mechanism: "PCT_OFF",
      depth_pct: 20,
      start_week: 105,
      duration_weeks: 4,
      target_segment: "All customers",
      bundle_partner_sku_id: null,
    },
    expected_units: 1540,
    promo_cost: 123456.4,
    expected_incremental_profit: -123456.4,
  },
];

export const awaitingApprovalSession: SessionResponse = {
  ...planningSession,
  status: "awaiting_approval",
  planning_request: {
    as_of_week: 104,
    scope: {
      regions: ["North", "West"],
      categories: ["Snacks"],
      sku_ids: [],
    },
    promo_window: { start_week: 105, end_week: 108 },
    marketing_budget: 200000,
    min_margin: null,
  },
  plan_revision: { number: 1, lines: planLines },
};

export const failedSession: SessionResponse = {
  ...planningSession,
  status: "failed",
  error: "The brief could not be planned: the brief states no marketing budget",
};
