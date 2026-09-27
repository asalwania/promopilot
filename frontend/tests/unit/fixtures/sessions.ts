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
    why_chosen: {
      reasons: [{ code: "clearance_value", amount: 20000 }],
      value: 6187.5,
      best_for_sku_region: true,
    },
    // Each mechanism's best option, the line's own shown with the line (ADR 0041).
    mechanism_comparison: [
      {
        mechanism: "PCT_OFF",
        chosen: true,
        best: {
          option: {
            sku_id: "SKU0003",
            region: "North",
            mechanism: "PCT_OFF",
            depth_pct: 20,
            start_week: 105,
            duration_weeks: 4,
            target_segment: "All customers",
            bundle_partner_sku_id: null,
          },
          anchor_sku_id: "SKU0003",
          partner_sku_id: null,
          basket_lift: null,
          effective_price: 80,
          partner_effective_price: null,
          units: 812.5,
          revenue: 65000,
          gross_profit: 16250,
          margin: 0.25,
          promo_cost: 13812.5,
          incremental_profit: -13812.5,
          cannibalised_profit: 0,
          halo_profit: 0,
          clearance_value: 20000,
          value: 6187.5,
        },
        unavailable: [],
      },
      {
        mechanism: "BUNDLE",
        chosen: false,
        best: {
          option: {
            sku_id: "SKU0003",
            region: "North",
            mechanism: "BUNDLE",
            depth_pct: 15,
            start_week: 105,
            duration_weeks: 2,
            target_segment: "Families",
            bundle_partner_sku_id: "SKU0042",
          },
          anchor_sku_id: "SKU0003",
          partner_sku_id: "SKU0042",
          basket_lift: 2.4,
          effective_price: 85,
          partner_effective_price: 42.5,
          units: 300,
          revenue: 38250,
          gross_profit: 9000,
          margin: 0.2353,
          promo_cost: 6250,
          incremental_profit: -2100,
          cannibalised_profit: 120,
          halo_profit: 340,
          clearance_value: 7200,
          value: 5320,
        },
        unavailable: [],
      },
      {
        mechanism: "BOGO",
        chosen: false,
        best: null,
        unavailable: ["below_cost"],
      },
    ],
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
    why_chosen: {
      reasons: [{ code: "clearance_value", amount: 130000 }],
      value: 6543.6,
      best_for_sku_region: false,
    },
    mechanism_comparison: [],
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
  plan_revision: {
    number: 1,
    lines: planLines,
    solver_status: "OPTIMAL",
    objective: 12731.1,
    binding_constraints: [
      {
        kind: "marketing_budget",
        source: "brief",
        limit: 200000,
        evidence: "exact",
        objective_gain: 812.4,
      },
    ],
    not_selected: [
      {
        option: {
          sku_id: "SKU0007",
          region: "North",
          mechanism: "BOGO",
          depth_pct: 50,
          start_week: 105,
          duration_weeks: 2,
          target_segment: "Families",
          bundle_partner_sku_id: null,
        },
        value: -250,
        reasons: ["low_uplift"],
        cannibalises: [],
      },
    ],
  },
};

export const failedSession: SessionResponse = {
  ...planningSession,
  status: "failed",
  error: "The brief could not be planned: the brief states no marketing budget",
};
