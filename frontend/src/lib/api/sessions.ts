import { z } from "zod";

import type { components } from "@/lib/api/schema";

type Schemas = components["schemas"];

// Runtime validation for the session contract; `satisfies` makes tsc fail if the
// OpenAPI-generated types (make api-types) drift from these schemas.
export const sessionCreatedSchema = z.object({
  session_id: z.string(),
}) satisfies z.ZodType<Schemas["SessionCreated"]>;

const regionSchema = z.enum([
  "North",
  "South",
  "East",
  "West",
]) satisfies z.ZodType<Schemas["Region"]>;

export const planLineSchema = z.object({
  sku_id: z.string(),
  region: regionSchema,
  mechanism: z.enum(["PCT_OFF", "BOGO", "BUNDLE", "FIXED_PRICE"]),
  depth_pct: z.number(),
  start_week: z.number(),
  duration_weeks: z.number(),
  target_segment: z.enum([
    "Value Seekers",
    "Families",
    "Premium",
    "Young Urban",
    "All customers",
  ]),
  bundle_partner_sku_id: z.string().nullable().optional(),
}) satisfies z.ZodType<Schemas["PlanLine"]>;

// Why the optimiser chose each plan line and left the others out (ADR 0038, ADR 0040).
export const whyChosenSchema = z.object({
  reasons: z.array(
    z.object({
      code: z.enum([
        "incremental_profit",
        "clearance_value",
        "halo",
        "clearance_target",
      ]),
      amount: z.number(),
    }),
  ),
  value: z.number(),
  best_for_sku_region: z.boolean(),
}) satisfies z.ZodType<Schemas["WhyChosen"]>;

const constraintKindSchema = z.enum([
  "marketing_budget",
  "minimum_margin",
  "margin_floor",
  "max_promoted_skus",
  "regional_budget",
  "clearance_target",
  "kvi_price_tolerance",
]);

const constraintSourceSchema = z.enum(["brief", "company_policy"]);

export const bindingConstraintSchema = z.object({
  kind: constraintKindSchema,
  source: constraintSourceSchema,
  limit: z.number(),
  category: z.string().nullable().optional(),
  region: regionSchema.nullable().optional(),
  sku_id: z.string().nullable().optional(),
  evidence: z.enum(["exact", "lower_bound", "unproven", "infeasible"]),
  objective_gain: z.number().nullable(),
}) satisfies z.ZodType<Schemas["BindingConstraint"]>;

// The smallest change to an infeasible request's brief constraints (ADR 0044).
export const relaxationSchema = z.object({
  changes: z.array(
    z.object({
      kind: constraintKindSchema,
      source: constraintSourceSchema,
      region: regionSchema.nullable().optional(),
      sku_id: z.string().nullable().optional(),
      current: z.number(),
      relaxed: z.number().nullable(),
      change: z.number(),
      policy_allows: z.number().nullable().optional(),
    }) satisfies z.ZodType<Schemas["RelaxedConstraint"]>,
  ),
  policy_binds: z.boolean(),
  proven: z.boolean(),
}) satisfies z.ZodType<Schemas["Relaxation"]>;

export const notSelectedOptionSchema = z.object({
  option: planLineSchema,
  value: z.number(),
  reasons: z.array(
    z.enum([
      "low_uplift",
      "out_of_stock",
      "breaks_policy",
      "over_budget",
      "over_regional_budget",
      "breaks_margin",
      "max_promoted_skus",
      "misses_clearance_target",
      "breaks_kvi_tolerance",
      "cannibalises",
      "time_limit",
    ]),
  ),
  cannibalises: z.array(z.string()),
}) satisfies z.ZodType<Schemas["NotSelectedOption"]>;

// Each mechanism's best option for a plan line's SKU and region (F-02, ADR 0041).
export const mechanismOptionSchema = z.object({
  option: planLineSchema,
  anchor_sku_id: z.string(),
  partner_sku_id: z.string().nullable().optional(),
  basket_lift: z.number().nullable().optional(),
  effective_price: z.number(),
  partner_effective_price: z.number().nullable().optional(),
  units: z.number(),
  revenue: z.number(),
  gross_profit: z.number(),
  margin: z.number(),
  promo_cost: z.number(),
  incremental_profit: z.number(),
  cannibalised_profit: z.number(),
  halo_profit: z.number(),
  clearance_value: z.number(),
  value: z.number(),
}) satisfies z.ZodType<Schemas["MechanismOption"]>;

export const mechanismOutcomeSchema = z.object({
  mechanism: planLineSchema.shape.mechanism,
  best: mechanismOptionSchema.nullable(),
  chosen: z.boolean(),
  unavailable: z.array(
    z.enum([
      "no_charm_price",
      "max_discount",
      "below_cost",
      "duplicate_price",
      "stock",
      "partner_stock",
    ]),
  ),
}) satisfies z.ZodType<Schemas["MechanismOutcome"]>;

// A clearance target no plan reaches, and a brief value company policy overrode (ADR 0040).
export const clearanceShortfallSchema = z.object({
  sku_id: z.string(),
  region: regionSchema,
  target: z.number(),
  expected_sell_through: z.number(),
  shortfall_units: z.number(),
}) satisfies z.ZodType<Schemas["ClearanceShortfall"]>;

export const policyFindingSchema = z.object({
  field: z.string(),
  requested: z.number(),
  applied: z.number(),
  message: z.string(),
}) satisfies z.ZodType<Schemas["PolicyFinding"]>;

// A violation the Critic left open on the plan revision (ADR 0046).
export const violationSchema = z.object({
  kind: z.literal("violation"),
  code: z.enum([
    "BUDGET",
    "REGIONAL_BUDGET",
    "MIN_MARGIN",
    "MARGIN_FLOOR",
    "STOCK",
    "MAX_DISCOUNT",
    "BELOW_COST",
    "WINDOW",
    "MAX_SKUS",
    "DUPLICATE_LINE",
    "CLEARANCE_TARGET",
    "KVI_TOLERANCE",
  ]),
  message: z.string(),
  sku_id: z.string().nullable().optional(),
  region: regionSchema.nullable().optional(),
  actual: z.number().nullable().optional(),
  limit: z.number().nullable().optional(),
}) satisfies z.ZodType<Schemas["Violation"]>;

// A risk the Critic's review found and left open, with its feedback (ADR 0051).
export const riskFindingSchema = z.object({
  kind: z.literal("risk"),
  code: z.enum([
    "OVER_CONCENTRATION",
    "HEAVY_CANNIBALISATION",
    "STOCKOUT_RISK",
  ]),
  message: z.string(),
  feedback: z.string(),
  sku_id: z.string().nullable().optional(),
  region: regionSchema.nullable().optional(),
  category: z.string().nullable().optional(),
  actual: z.number(),
  limit: z.number(),
}) satisfies z.ZodType<Schemas["RiskFinding"]>;

export const openIssueSchema = z.discriminatedUnion("kind", [
  violationSchema,
  riskFindingSchema,
]) satisfies z.ZodType<Schemas["OpenIssue"]>;

// One approval or rejection of a plan revision: the session's audit trail (ADR 0046).
export const planDecisionSchema = z.object({
  decision: z.enum(["approved", "rejected"]),
  revision_number: z.number(),
  reason: z.string().nullable().optional(),
  decided_at: z.string(),
}) satisfies z.ZodType<Schemas["PlanDecision"]>;

export const assumptionSchema = z.object({
  field: z.string(),
  value: z.string(),
  source: z.enum(["brief", "data", "default"]),
  confidence: z.number(),
  flagged: z.boolean(),
  note: z.string().nullable().optional(),
  // Read by rules while the LLM was unavailable (ADR 0053).
  fallback: z.boolean(),
}) satisfies z.ZodType<Schemas["Assumption"]>;

export const clarificationQuestionSchema = z.object({
  id: z.string(),
  field: z.string(),
  question: z.string(),
  reason: z.enum(["missing", "low_confidence", "ambiguous"]),
  suggestions: z.array(z.string()),
}) satisfies z.ZodType<Schemas["ClarificationQuestion"]>;

export const clarificationSchema = z.object({
  question: clarificationQuestionSchema,
  answer: z.string(),
}) satisfies z.ZodType<Schemas["Clarification"]>;

export const planRevisionLineSchema = z.object({
  line: planLineSchema,
  expected_units: z.number(),
  promo_cost: z.number(),
  expected_incremental_profit: z.number(),
  why_chosen: whyChosenSchema.nullable().optional(),
  mechanism_comparison: z.array(mechanismOutcomeSchema),
  // Null or empty for lines planned before #60 (ADR 0060).
  baseline_units: z.number().nullable().optional(),
  uplift_pct: z.number().nullable().optional(),
  segments: z.array(
    z.object({
      segment: z.enum(["Value Seekers", "Families", "Premium", "Young Urban"]),
      units: z.number(),
      baseline_units: z.number(),
      uplift_pct: z.number().nullable(),
    }) satisfies z.ZodType<Schemas["SegmentUplift"]>,
  ),
  cross_effects: z.array(
    z.object({
      sku_id: z.string(),
      units_change_pct: z.number(),
      profit_change: z.number(),
    }) satisfies z.ZodType<Schemas["LineCrossEffect"]>,
  ),
}) satisfies z.ZodType<Schemas["PlanRevisionLine"]>;

const percentilesSchema = z.object({
  p10: z.number(),
  p50: z.number(),
  p90: z.number(),
}) satisfies z.ZodType<Schemas["Percentiles"]>;

const simulatedOutcomesShape = {
  units: percentilesSchema,
  revenue: percentilesSchema,
  gross_profit: percentilesSchema,
  margin: percentilesSchema,
  promo_spend: percentilesSchema,
  sell_through: percentilesSchema.nullable(),
};

// The Monte Carlo simulation stored with a plan revision (ADR 0042).
export const planSimulationSchema = z.object({
  n_runs: z.number(),
  seed: z.number(),
  lines: z.array(
    z.object({
      ...simulatedOutcomesShape,
      sku_id: z.string(),
      region: regionSchema,
      stockout_probability: z.number(),
    }) satisfies z.ZodType<Schemas["LineSimulation"]>,
  ),
  total: z.object(simulatedOutcomesShape) satisfies z.ZodType<
    Schemas["SimulatedOutcomes"]
  >,
  regions: z.array(
    z.object({
      region: regionSchema,
      stockout_probability: z.number(),
    }) satisfies z.ZodType<Schemas["RegionStockout"]>,
  ),
}) satisfies z.ZodType<Schemas["PlanSimulation"]>;

// What the Explainer wrote: grounded by the LLM, or the template fallback (ADR 0050).
export const planExplanationSchema = z.object({
  summary: z.string(),
  rationales: z.array(z.string()),
  source: z.enum(["llm", "template"]),
  fallback_reason: z
    .enum(["ungrounded", "invalid_answer", "llm_unavailable"])
    .nullable()
    .optional(),
  changes: z.string().nullable().optional(),
}) satisfies z.ZodType<Schemas["PlanExplanation"]>;

// What changed from the previous plan revision after an amendment (ADR 0052).
export const revisionDiffSchema = z.object({
  from_revision: z.number(),
  added: z.array(planRevisionLineSchema),
  removed: z.array(planRevisionLineSchema),
  changed: z.array(
    z.object({
      sku_id: z.string(),
      region: regionSchema,
      fields: z.array(z.string()),
      before: planRevisionLineSchema,
      after: planRevisionLineSchema,
    }) satisfies z.ZodType<Schemas["LineChange"]>,
  ),
  unchanged: z.number(),
  objective_before: z.number().nullable().optional(),
  objective_after: z.number().nullable().optional(),
  objective_delta: z.number().nullable().optional(),
  promo_cost_before: z.number(),
  promo_cost_after: z.number(),
  promo_cost_delta: z.number(),
  request_changes: z.array(
    z.object({
      field: z.string(),
      before: z.string(),
      after: z.string(),
    }) satisfies z.ZodType<Schemas["RequestChange"]>,
  ),
}) satisfies z.ZodType<Schemas["RevisionDiff"]>;

export const planRevisionSchema = z.object({
  number: z.number(),
  lines: z.array(planRevisionLineSchema),
  solver_status: z
    .enum(["OPTIMAL", "FEASIBLE", "INFEASIBLE"])
    .nullable()
    .optional(),
  objective: z.number().nullable().optional(),
  binding_constraints: z.array(bindingConstraintSchema),
  not_selected: z.array(notSelectedOptionSchema),
  simulation: planSimulationSchema.nullable().optional(),
  clearance_shortfalls: z.array(clearanceShortfallSchema),
  policy_findings: z.array(policyFindingSchema),
  relaxation: relaxationSchema.nullable().optional(),
  open_issues: z.array(openIssueSchema),
  explanation: planExplanationSchema.nullable().optional(),
  diff: revisionDiffSchema.nullable().optional(),
}) satisfies z.ZodType<Schemas["PlanRevision"]>;

export const planningRequestSchema = z.object({
  as_of_week: z.number(),
  scope: z.object({
    regions: z.array(regionSchema),
    categories: z.array(z.string()),
    sku_ids: z.array(z.string()),
  }),
  promo_window: z.object({ start_week: z.number(), end_week: z.number() }),
  marketing_budget: z.number(),
  min_margin: z.number().nullable().optional(),
  clearance_targets: z.array(
    z.object({ sku_id: z.string(), sell_through: z.number() }),
  ),
  regional_budget_caps: z.record(z.string(), z.number()).optional(),
  kvi_price_tolerance: z.number().nullable().optional(),
  max_promoted_skus_per_category_per_region: z.number().nullable().optional(),
}) satisfies z.ZodType<Schemas["PlanningRequest"]>;

// A change to the planning request, kept oldest first (ADR 0052).
export const amendmentSchema = z.object({
  text: z.string(),
  amends_revision: z.number(),
  relaxation: relaxationSchema.nullable().optional(),
  amended_at: z.string(),
}) satisfies z.ZodType<Schemas["Amendment"]>;

// What a session's LLM calls used and cost: the sums of its token-usage trace
// events (ADR 0047).
const sessionUsageSchema = z.object({
  calls: z.number(),
  input_tokens: z.number(),
  output_tokens: z.number(),
  cost_usd: z.number(),
  cost_inr: z.number(),
  unpriced_models: z.array(z.string()),
}) satisfies z.ZodType<Schemas["SessionUsage"]>;

export const sessionSchema = z.object({
  session_id: z.string(),
  status: z.enum([
    "planning",
    "awaiting_clarification",
    "awaiting_approval",
    "approved",
    "rejected",
    "failed",
  ]),
  brief: z.string(),
  planning_request: planningRequestSchema.nullable(),
  plan_revision: planRevisionSchema.nullable(),
  error: z.string().nullable(),
  decisions: z.array(planDecisionSchema),
  usage: sessionUsageSchema,
  assumptions: z.array(assumptionSchema),
  questions: z.array(clarificationQuestionSchema),
  clarifications: z.array(clarificationSchema),
  amendments: z.array(amendmentSchema),
}) satisfies z.ZodType<Schemas["SessionResponse"]>;

export type Session = z.infer<typeof sessionSchema>;
export type SessionStatus = Session["status"];
export type SessionUsage = Session["usage"];
export type PlanRevisionLine = z.infer<typeof planRevisionLineSchema>;
export type PlanRevision = z.infer<typeof planRevisionSchema>;
export type PlanSimulation = z.infer<typeof planSimulationSchema>;
export type LineSimulation = PlanSimulation["lines"][number];
export type MechanismOutcome = z.infer<typeof mechanismOutcomeSchema>;
export type PlanExplanation = z.infer<typeof planExplanationSchema>;
export type Region = PlanRevisionLine["line"]["region"];
export type PlanningRequest = z.infer<typeof planningRequestSchema>;
export type PlanDecision = z.infer<typeof planDecisionSchema>;
export type ClarificationQuestion = z.infer<typeof clarificationQuestionSchema>;
export type Clarification = z.infer<typeof clarificationSchema>;
export type Assumption = z.infer<typeof assumptionSchema>;
export type Amendment = z.infer<typeof amendmentSchema>;
export type RevisionDiff = z.infer<typeof revisionDiffSchema>;
export type LineChange = RevisionDiff["changed"][number];

export type CreateSessionResult =
  { ok: true; sessionId: string } | { ok: false; reason: string };

// Browser-side: goes through the same-origin `/api/*` proxy (ADR 0018).
export async function createSession(
  brief: string,
  fetchImpl: typeof fetch = fetch,
): Promise<CreateSessionResult> {
  try {
    const response = await fetchImpl("/api/sessions", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ brief }),
    });
    if (response.status === 422) {
      return { ok: false, reason: await validationMessage(response) };
    }
    if (!response.ok) {
      return { ok: false, reason: `HTTP ${response.status}` };
    }
    const created = sessionCreatedSchema.safeParse(await response.json());
    if (!created.success) {
      return { ok: false, reason: "unexpected session response" };
    }
    return { ok: true, sessionId: created.data.session_id };
  } catch (error) {
    return { ok: false, reason: errorMessage(error) };
  }
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

const validationErrorSchema = z.object({
  detail: z.array(z.object({ msg: z.string() })).min(1),
});

async function validationMessage(response: Response): Promise<string> {
  const parsed = validationErrorSchema.safeParse(await response.json());
  return parsed.success ? parsed.data.detail[0].msg : "HTTP 422";
}

// What a session action (clarify, amend, approve, reject) answered: the session as
// the API now holds it, or why it failed. A conflict (409) means the session moved on,
// so the page reloads it (ADR 0061 D9, ADR 0066).
export type SessionActionResult =
  | { ok: true; session: Session }
  | { ok: false; reason: string; conflict: boolean };

export type ClarifyResult = SessionActionResult;

// Answers every open question by its id (ADR 0048). A 202 carries the session, back
// in `planning`; a 409 means the questions were already answered (ADR 0061).
export function clarifySession(
  sessionId: string,
  answers: Record<string, string>,
  fetchImpl: typeof fetch = fetch,
): Promise<SessionActionResult> {
  return postSessionAction(sessionId, "clarify", { answers }, fetchImpl, {
    conflictReason: "These questions were already answered.",
  });
}

// An amendment in the manager's words, or accepting the latest revision's smallest
// relaxation (ADR 0044, ADR 0052 D7).
export type AmendInput = { text: string } | { acceptRelaxation: true };

// Amends the planning request of a session awaiting approval, or rejected (ADR 0052).
// A 202 carries the session, back in `planning`, while the new revision is planned.
export function amendSession(
  sessionId: string,
  amendment: AmendInput,
  fetchImpl: typeof fetch = fetch,
): Promise<SessionActionResult> {
  const body =
    "text" in amendment
      ? { text: amendment.text }
      : { accept_relaxation: true };
  return postSessionAction(sessionId, "amend", body, fetchImpl);
}

// Approves the shown plan revision, which must be the latest (ADR 0046 D7); the
// session is then final.
export function approveSession(
  sessionId: string,
  revisionNumber: number,
  fetchImpl: typeof fetch = fetch,
): Promise<SessionActionResult> {
  return postSessionAction(
    sessionId,
    "approve",
    { revision_number: revisionNumber },
    fetchImpl,
  );
}

// Rejects the shown plan revision with a reason; the session stays open for an
// amendment (ADR 0046 D9).
export function rejectSession(
  sessionId: string,
  revisionNumber: number,
  reason: string,
  fetchImpl: typeof fetch = fetch,
): Promise<SessionActionResult> {
  return postSessionAction(
    sessionId,
    "reject",
    { revision_number: revisionNumber, reason },
    fetchImpl,
  );
}

// Posts one action to the same-origin proxy. Every action answers with the session;
// a failure carries the API's `detail`, or a fixed conflict reason when given.
async function postSessionAction(
  sessionId: string,
  action: "clarify" | "amend" | "approve" | "reject",
  body: unknown,
  fetchImpl: typeof fetch,
  { conflictReason }: { conflictReason?: string } = {},
): Promise<SessionActionResult> {
  try {
    const response = await fetchImpl(
      `/api/sessions/${encodeURIComponent(sessionId)}/${action}`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      },
    );
    if (!response.ok) {
      const conflict = response.status === 409;
      return {
        ok: false,
        conflict,
        reason:
          conflict && conflictReason
            ? conflictReason
            : await detailMessage(response),
      };
    }
    const parsed = sessionSchema.safeParse(await response.json());
    if (!parsed.success) {
      return {
        ok: false,
        conflict: false,
        reason: "unexpected session response",
      };
    }
    return { ok: true, session: parsed.data };
  } catch (error) {
    return { ok: false, conflict: false, reason: errorMessage(error) };
  }
}

const detailSchema = z.object({
  detail: z.union([
    z.string().min(1),
    z.array(z.object({ msg: z.string() })).min(1),
  ]),
});

// FastAPI's `detail`: a message from the handler, or the first validation error.
async function detailMessage(response: Response): Promise<string> {
  const fallback = `HTTP ${response.status}`;
  try {
    const parsed = detailSchema.safeParse(await response.json());
    if (!parsed.success) return fallback;
    const { detail } = parsed.data;
    return typeof detail === "string" ? detail : detail[0].msg;
  } catch {
    return fallback;
  }
}

export class SessionLoadError extends Error {
  constructor(
    message: string,
    readonly notFound = false,
  ) {
    super(message);
    this.name = "SessionLoadError";
  }
}

// Throws on any failure so TanStack Query can retry it and surface the error.
// Network errors from fetch propagate as they are.
export async function getSession(
  sessionId: string,
  fetchImpl: typeof fetch = fetch,
): Promise<Session> {
  const response = await fetchImpl(
    `/api/sessions/${encodeURIComponent(sessionId)}`,
    { cache: "no-store" },
  );
  if (response.status === 404) {
    throw new SessionLoadError("Session not found", true);
  }
  if (!response.ok) {
    throw new SessionLoadError(`HTTP ${response.status}`);
  }
  const parsed = sessionSchema.safeParse(await response.json());
  if (!parsed.success) {
    throw new SessionLoadError("unexpected session response");
  }
  return parsed.data;
}
