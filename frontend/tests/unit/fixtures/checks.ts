import type { components } from "@/lib/api/schema";

import { awaitingApprovalSession, infeasibleSession } from "./sessions";

type SessionResponse = components["schemas"]["SessionResponse"];
type PlanRevision = components["schemas"]["PlanRevision"];
type Relaxation = components["schemas"]["Relaxation"];

const plan = awaitingApprovalSession.plan_revision!;

// A revision the Critic handed on with hard constraints still broken (ADR 0051): one per
// checklist row but stock, and a risk finding, which is no constraint (ADR 0067).
export const brokenChecksSession: SessionResponse = {
  ...awaitingApprovalSession,
  planning_request: {
    ...awaitingApprovalSession.planning_request!,
    min_margin: 0.18,
    clearance_targets: [{ sku_id: "SKU0006", sell_through: 0.6 }],
  },
  plan_revision: {
    ...plan,
    open_issues: [
      {
        kind: "violation",
        code: "BUDGET",
        message:
          "total promo cost ₹2,10,000 exceeds the marketing budget ₹2,00,000",
        actual: 210000,
        limit: 200000,
      },
      {
        kind: "violation",
        code: "MIN_MARGIN",
        message:
          "blended expected margin 16.2% is below the minimum margin 18.0%",
        actual: 0.162,
        limit: 0.18,
      },
      {
        kind: "violation",
        code: "CLEARANCE_TARGET",
        message:
          "SKU0006 in North is expected to sell through 59.9% of its stock, below the clearance target 60.0%: short by 3 units",
        sku_id: "SKU0006",
        region: "North",
        actual: 0.599,
        limit: 0.6,
      },
      {
        kind: "violation",
        code: "MAX_DISCOUNT",
        message:
          "SKU0007 in West: effective discount 55% is deeper than the company-policy maximum 50%",
        sku_id: "SKU0007",
        region: "West",
        actual: 0.55,
        limit: 0.5,
      },
      {
        kind: "risk",
        code: "STOCKOUT_RISK",
        message:
          "SKU0013 in North runs out of stock in 24% of the simulated runs, at or above the 20% limit",
        feedback: "Promote SKU0013 in North less deeply.",
        sku_id: "SKU0013",
        region: "North",
        actual: 0.24,
        limit: 0.2,
      },
    ],
    policy_findings: [
      {
        field: "min_margin",
        requested: 0.1,
        applied: 0.15,
        message:
          "the brief's minimum margin of 10.0% is below the company-policy floor of 15.0%; the floor applies",
      },
    ],
  },
};

// The best options left out, one per reason the optimiser gives (ADR 0038, ADR 0040).
export const notSelected: PlanRevision["not_selected"] = [
  {
    option: {
      sku_id: "SKU0021",
      region: "West",
      mechanism: "BUNDLE",
      depth_pct: 15,
      start_week: 105,
      duration_weeks: 2,
      target_segment: "Families",
      bundle_partner_sku_id: "SKU0042",
    },
    value: 14250.4,
    reasons: ["over_budget", "cannibalises"],
    cannibalises: ["SKU0003", "SKU0011"],
  },
  {
    option: {
      sku_id: "SKU0007",
      region: "North",
      mechanism: "BOGO",
      depth_pct: 50,
      start_week: 106,
      duration_weeks: 3,
      target_segment: "All customers",
      bundle_partner_sku_id: null,
    },
    value: -250,
    reasons: ["low_uplift"],
    cannibalises: [],
  },
];

// A proven relaxation that lowers a clearance target company policy caps, raises the
// budget, drops a second target and turns the KVI tolerance off (ADR 0044).
export const policyBindingRelaxation: Relaxation = {
  changes: [
    {
      kind: "clearance_target",
      source: "brief",
      region: null,
      sku_id: "SKU0006",
      current: 0.6,
      relaxed: 0.5993,
      change: 0.0012,
      policy_allows: 0.5993,
    },
    {
      kind: "marketing_budget",
      source: "brief",
      region: null,
      sku_id: null,
      current: 200000,
      relaxed: 214500.25,
      change: 0.075,
      policy_allows: null,
    },
    {
      kind: "clearance_target",
      source: "brief",
      region: null,
      sku_id: "SKU0029",
      current: 0.5,
      relaxed: null,
      change: 1,
      policy_allows: null,
    },
    {
      kind: "kvi_price_tolerance",
      source: "brief",
      region: null,
      sku_id: null,
      current: 0.03,
      relaxed: null,
      change: 1,
      policy_allows: null,
    },
  ],
  policy_binds: true,
  proven: true,
};

export const infeasibleRevision: PlanRevision =
  infeasibleSession.plan_revision!;

// A solve that ran out of time with a shortfall: FEASIBLE, with an unproven relaxation.
export const timedOutRevision: PlanRevision = {
  ...infeasibleRevision,
  solver_status: "FEASIBLE",
  binding_constraints: [],
  relaxation: { ...infeasibleRevision.relaxation!, proven: false },
};
