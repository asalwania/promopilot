import type { components } from "@/lib/api/schema";

type SessionResponse = components["schemas"]["SessionResponse"];
type PlanRevisionLine = components["schemas"]["PlanRevisionLine"];
type CompetitorGap = components["schemas"]["CompetitorGap"];

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
  decisions: [],
  usage: {
    calls: 0,
    input_tokens: 0,
    output_tokens: 0,
    cost_usd: 0,
    cost_inr: 0,
    unpriced_models: [],
  },
  assumptions: [],
  questions: [],
  clarifications: [],
  amendments: [],
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
    baseline_units: 500,
    uplift_pct: 62.5,
    // Everyone is offered the line, so every segment lifts (F-03 AC2).
    segments: [
      {
        segment: "Value Seekers",
        units: 300,
        baseline_units: 150,
        uplift_pct: 100,
      },
      {
        segment: "Families",
        units: 262.5,
        baseline_units: 175,
        uplift_pct: 50,
      },
      { segment: "Premium", units: 100, baseline_units: 80, uplift_pct: 25 },
      {
        segment: "Young Urban",
        units: 150,
        baseline_units: 95,
        uplift_pct: 57.89,
      },
    ],
    // The SKUs it moves in North, largest profit change first (ADR 0033).
    cross_effects: [
      { sku_id: "SKU0004", units_change_pct: -12.5, profit_change: -3000 },
      { sku_id: "SKU0020", units_change_pct: 8, profit_change: 1200 },
      { sku_id: "SKU0005", units_change_pct: -0.4, profit_change: -35 },
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
    baseline_units: 1100,
    uplift_pct: 40,
    segments: [
      {
        segment: "Value Seekers",
        units: 440,
        baseline_units: 300,
        uplift_pct: 46.67,
      },
      {
        segment: "Families",
        units: 500,
        baseline_units: 350,
        uplift_pct: 42.86,
      },
      { segment: "Premium", units: 250, baseline_units: 200, uplift_pct: 25 },
      {
        segment: "Young Urban",
        units: 350,
        baseline_units: 250,
        uplift_pct: 40,
      },
    ],
    cross_effects: [],
  },
  {
    // The same SKU as the first line, customised for West (F-07 AC2).
    line: {
      sku_id: "SKU0003",
      region: "West",
      mechanism: "BOGO",
      depth_pct: 50,
      start_week: 106,
      duration_weeks: 2,
      target_segment: "Families",
      bundle_partner_sku_id: null,
    },
    expected_units: 420,
    promo_cost: 9100,
    expected_incremental_profit: 4250,
    why_chosen: {
      reasons: [{ code: "incremental_profit", amount: 4250 }],
      value: 4250,
      best_for_sku_region: true,
    },
    mechanism_comparison: [],
    baseline_units: 300,
    uplift_pct: 40,
    // A Families-only offer lifts only Families.
    segments: [
      {
        segment: "Value Seekers",
        units: 90,
        baseline_units: 90,
        uplift_pct: 0,
      },
      {
        segment: "Families",
        units: 210,
        baseline_units: 90,
        uplift_pct: 133.33,
      },
      { segment: "Premium", units: 50, baseline_units: 50, uplift_pct: 0 },
      { segment: "Young Urban", units: 70, baseline_units: 70, uplift_pct: 0 },
    ],
    cross_effects: [],
  },
];

// A line planned before #60 kept no uplift, segments or cross effects.
export const legacyPlanLine: PlanRevisionLine = {
  ...planLines[1],
  baseline_units: null,
  uplift_pct: null,
  segments: [],
  cross_effects: [],
};

// As GET /api/competitors/gaps?as_of_week=104&kvi_only=true returns them (ADR 0031).
export const undercutGaps: CompetitorGap[] = [
  {
    region: "North",
    sku_id: "SKU0003",
    name: "Masala Chips 150g",
    category: "Snacks",
    subcategory: "Chips",
    is_kvi: true,
    base_price: 100,
    competitor_price: 88,
    competitor_on_promo: false,
    price_week: 103,
    cpi: 0.88,
    gap: 0.12,
    undercut: true,
  },
  {
    region: "West",
    sku_id: "SKU0011",
    name: "Cola 750ml",
    category: "Beverages",
    subcategory: "Soft drinks",
    is_kvi: true,
    base_price: 40,
    competitor_price: 39,
    competitor_on_promo: false,
    price_week: 103,
    cpi: 0.975,
    gap: 0.025,
    undercut: false,
  },
];

export const awaitingApprovalSession: SessionResponse = {
  ...planningSession,
  status: "awaiting_approval",
  usage: {
    calls: 3,
    input_tokens: 45_210,
    output_tokens: 1830,
    cost_usd: 0.021,
    cost_inr: 2.02,
    unpriced_models: [],
  },
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
    clearance_targets: [],
    regional_budget_caps: {},
    kvi_price_tolerance: null,
    max_promoted_skus_per_category_per_region: null,
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
    simulation: {
      n_runs: 1000,
      seed: 0,
      lines: [
        {
          sku_id: "SKU0003",
          region: "North",
          units: { p10: 700, p50: 810, p90: 830 },
          revenue: { p10: 56000, p50: 64800, p90: 66400 },
          gross_profit: { p10: 11200, p50: 12960, p90: 13280 },
          margin: { p10: 0.2, p50: 0.2, p90: 0.2 },
          promo_spend: { p10: 12000, p50: 13800, p90: 14100 },
          sell_through: { p10: 0.84, p50: 0.98, p90: 1 },
          stockout_probability: 0.31,
        },
        {
          sku_id: "SKU0011",
          region: "West",
          units: { p10: 1400, p50: 1538, p90: 1690 },
          revenue: { p10: 112000, p50: 123040, p90: 135200 },
          gross_profit: { p10: 22400, p50: 24608, p90: 27040 },
          margin: { p10: 0.2, p50: 0.2, p90: 0.2 },
          promo_spend: { p10: 112000, p50: 123000, p90: 135000 },
          sell_through: null,
          stockout_probability: 0,
        },
        {
          sku_id: "SKU0003",
          region: "West",
          units: { p10: 350, p50: 418, p90: 470 },
          revenue: { p10: 17500, p50: 20900, p90: 23500 },
          gross_profit: { p10: 3500, p50: 4180, p90: 4700 },
          margin: { p10: 0.2, p50: 0.2, p90: 0.2 },
          promo_spend: { p10: 8000, p50: 9100, p90: 10000 },
          sell_through: { p10: 0.5, p50: 0.6, p90: 0.67 },
          stockout_probability: 0.05,
        },
      ],
      total: {
        units: { p10: 2150, p50: 2348, p90: 2500 },
        revenue: { p10: 172000, p50: 187840, p90: 200000 },
        gross_profit: { p10: 34400, p50: 37568, p90: 40000 },
        margin: { p10: 0.2, p50: 0.2, p90: 0.2 },
        promo_spend: { p10: 125000, p50: 136800, p90: 148000 },
        sell_through: { p10: 0.84, p50: 0.98, p90: 1 },
      },
      regions: [
        { region: "North", stockout_probability: 0.31 },
        { region: "West", stockout_probability: 0.05 },
      ],
    },
    clearance_shortfalls: [],
    policy_findings: [],
    open_issues: [],
    explanation: {
      summary:
        "Two lines across North and West, expected to add ₹12,731 within a ₹2 lakh budget.",
      rationales: [
        "SKU0003 in North at 20% off is the best option for its SKU and region.",
        "SKU0011 in West clears overstock at 20% off.",
        "SKU0003 in West sells best to Families as a BOGO.",
      ],
      source: "llm",
      fallback_reason: null,
      competitor_response: [],
    },
  },
};

export const failedSession: SessionResponse = {
  ...planningSession,
  status: "failed",
  error: "The brief could not be planned: the brief states no marketing budget",
};

// A request no plan can reach every clearance target of, and its relaxation (ADR 0044).
export const infeasibleSession: SessionResponse = {
  ...awaitingApprovalSession,
  plan_revision: {
    number: 1,
    lines: [],
    solver_status: "INFEASIBLE",
    objective: 0,
    binding_constraints: [
      {
        kind: "marketing_budget",
        source: "brief",
        limit: 200000,
        evidence: "infeasible",
        objective_gain: null,
      },
      {
        kind: "clearance_target",
        source: "brief",
        limit: 0.5,
        sku_id: "SKU0029",
        region: "North",
        evidence: "infeasible",
        objective_gain: null,
      },
    ],
    not_selected: [],
    clearance_shortfalls: [
      {
        sku_id: "SKU0029",
        region: "North",
        target: 0.5,
        expected_sell_through: 0.42,
        shortfall_units: 96,
      },
    ],
    policy_findings: [],
    open_issues: [],
    relaxation: {
      changes: [
        {
          kind: "marketing_budget",
          source: "brief",
          region: null,
          sku_id: null,
          current: 200000,
          relaxed: 214500,
          change: 0.0725,
          policy_allows: null,
        },
      ],
      policy_binds: false,
      proven: true,
    },
    explanation: {
      summary:
        "Plan revision 1. Infeasible: no plan reaches every clearance target within the brief's constraints, so this is the closest plan.",
      rationales: [],
      source: "template",
      fallback_reason: "llm_unavailable",
      competitor_response: [],
    },
  },
};

// The Context agent asks instead of guessing (ADR 0048).
export const awaitingClarificationSession: SessionResponse = {
  ...planningSession,
  status: "awaiting_clarification",
  assumptions: [
    {
      field: "scope.regions",
      value: "North, West",
      source: "brief",
      confidence: 1,
      flagged: false,
      note: null,
      fallback: false,
    },
  ],
  questions: [
    {
      id: "marketing_budget",
      field: "marketing_budget",
      question:
        "What marketing budget should the plan's promo cost stay within, in rupees?",
      reason: "missing",
      suggestions: [],
    },
    {
      id: "scope.categories",
      field: "scope.categories",
      question: 'Which product categories does "snak stuff" mean?',
      reason: "low_confidence",
      suggestions: ["Snacks"],
    },
  ],
};

export const approvedSession: SessionResponse = {
  ...awaitingApprovalSession,
  status: "approved",
  decisions: [
    {
      decision: "approved",
      revision_number: 1,
      reason: null,
      decided_at: "2026-09-28T10:15:00Z",
    },
  ],
};

export const rejectedSession: SessionResponse = {
  ...awaitingApprovalSession,
  status: "rejected",
  decisions: [
    {
      decision: "rejected",
      revision_number: 1,
      reason: "Too deep on Beverages in West.",
      decided_at: "2026-09-28T10:15:00Z",
    },
  ],
};

// A revision the Critic handed on with a violation and a risk finding still open (ADR 0051).
export const openIssuesSession: SessionResponse = {
  ...awaitingApprovalSession,
  plan_revision: {
    ...awaitingApprovalSession.plan_revision!,
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
        kind: "risk",
        code: "STOCKOUT_RISK",
        message:
          "SKU0013 in North runs out of stock in 24% of the simulated runs, at or above the 20% limit",
        feedback:
          "Promote SKU0013 in North less deeply, or leave SKU0013 out of generate_candidates' sku_ids.",
        sku_id: "SKU0013",
        region: "North",
        actual: 0.24,
        limit: 0.2,
      },
    ],
  },
};

type Assumption = components["schemas"]["Assumption"];

// What the Context agent read (ADR 0048): exact readings, a fuzzy one, a brief value
// company policy overrode, a policy default and a fact from data.
export const contextAssumptions: Assumption[] = [
  {
    field: "scope.regions",
    value: "North, West",
    source: "brief",
    confidence: 1,
    flagged: false,
    note: null,
    fallback: false,
  },
  {
    field: "scope.categories",
    value: "Snacks",
    source: "brief",
    confidence: 0.83,
    flagged: false,
    note: null,
    fallback: false,
  },
  {
    field: "marketing_budget",
    value: "₹200,000",
    source: "brief",
    confidence: 1,
    flagged: false,
    note: null,
    fallback: false,
  },
  {
    field: "min_margin",
    value: "15.0% (company policy; the brief asked for 5.0%)",
    source: "brief",
    confidence: 1,
    flagged: true,
    note: "The brief's minimum margin of 5.0% is below the company-policy floor of 15.0%; the floor applies.",
    fallback: false,
  },
  {
    field: "kvi_price_tolerance",
    value: "5.0% (company policy)",
    source: "default",
    confidence: 1,
    flagged: false,
    note: null,
    fallback: false,
  },
  {
    field: "overstocked_skus",
    value: "SKU0003 in North",
    source: "data",
    confidence: 1,
    flagged: false,
    note: null,
    fallback: false,
  },
];

// The same brief read by rules while the language model was down (ADR 0053).
export const fallbackAssumptions: Assumption[] = [
  {
    field: "scope.regions",
    value: "North, West",
    source: "brief",
    confidence: 0.7,
    flagged: false,
    note: "Read by rules: the language model was unavailable.",
    fallback: true,
  },
  {
    field: "as_of_week",
    value: "week 104 (starts 2026-09-21)",
    source: "data",
    confidence: 1,
    flagged: false,
    note: null,
    fallback: true,
  },
];

// A second round: the first answer could not be read, so the budget is asked again.
export const repeatedQuestionSession: SessionResponse = {
  ...awaitingClarificationSession,
  questions: [
    {
      id: "marketing_budget",
      field: "marketing_budget",
      question:
        'The marketing budget reads as "2 laks". What budget should the plan\'s promo cost stay within, in rupees?',
      reason: "low_confidence",
      suggestions: [],
    },
  ],
  clarifications: [
    {
      question: awaitingClarificationSession.questions[0],
      answer: "2 laks",
    },
  ],
};

// The amendment "Budget cut to ₹1.5 lakh" of plan revision 1 (ADR 0052). Revision 2
// drops SKU0011 in West, cuts SKU0003 in North to 15% off, adds
// SKU0020 in North and keeps SKU0003 in West as it was.
const budgetCut = {
  text: "Budget cut to ₹1.5 lakh",
  amends_revision: 1,
  relaxation: null,
  amended_at: "2026-09-28T10:20:00Z",
};

const shallowerNorth: PlanRevisionLine = {
  ...planLines[0],
  line: { ...planLines[0].line, depth_pct: 15 },
  promo_cost: 9000,
  expected_incremental_profit: -8000,
};

const addedNorth: PlanRevisionLine = {
  ...planLines[2],
  line: {
    ...planLines[2].line,
    sku_id: "SKU0020",
    region: "North",
    mechanism: "PCT_OFF",
    depth_pct: 10,
    start_week: 105,
    duration_weeks: 3,
    target_segment: "All customers",
  },
  promo_cost: 4500,
  expected_incremental_profit: 2600,
};

export const amendedSession: SessionResponse = {
  ...awaitingApprovalSession,
  planning_request: {
    ...awaitingApprovalSession.planning_request!,
    marketing_budget: 150000,
  },
  plan_revision: {
    ...awaitingApprovalSession.plan_revision!,
    number: 2,
    lines: [shallowerNorth, addedNorth, planLines[2]],
    objective: 9800,
    simulation: null,
    explanation: {
      ...awaitingApprovalSession.plan_revision!.explanation!,
      rationales: [
        "SKU0003 in North at 15% off fits the smaller budget.",
        "SKU0020 in North at 10% off adds ₹2,600.",
        "SKU0003 in West sells best to Families as a BOGO.",
      ],
      changes:
        "Plan revision 2 changes plan revision 1. The marketing budget went from ₹2 lakh to ₹1.5 lakh, so SKU0011 in West was removed.",
    },
    diff: {
      from_revision: 1,
      added: [addedNorth],
      removed: [planLines[1]],
      changed: [
        {
          sku_id: "SKU0003",
          region: "North",
          fields: ["depth_pct"],
          before: planLines[0],
          after: shallowerNorth,
        },
      ],
      unchanged: 1,
      objective_before: 12731.1,
      objective_after: 9800,
      objective_delta: -2931.1,
      promo_cost_before: 146368.9,
      promo_cost_after: 22600,
      promo_cost_delta: -123768.9,
      request_changes: [
        { field: "marketing_budget", before: "₹2 lakh", after: "₹1.5 lakh" },
      ],
    },
  },
  amendments: [budgetCut],
};

// The same amendment just sent: the Planner is at work, and the read model still holds
// plan revision 1 until the new round's revision is saved (ADR 0052 D10).
export const replanningSession: SessionResponse = {
  ...awaitingApprovalSession,
  status: "planning",
  amendments: [budgetCut],
};

// Revision 1 rejected, then amended; revision 2 approved: the audit trail (ADR 0046 D8).
export const approvedAfterAmendmentSession: SessionResponse = {
  ...amendedSession,
  status: "approved",
  decisions: [
    {
      decision: "rejected",
      revision_number: 1,
      reason: "Too deep on Beverages in West.",
      decided_at: "2026-09-28T10:15:00Z",
    },
    {
      decision: "approved",
      revision_number: 2,
      reason: null,
      decided_at: "2026-09-28T10:30:00Z",
    },
  ],
};
