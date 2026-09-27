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

// Why the optimiser chose each plan line and left the others out (ADR 0038).
export const whyChosenSchema = z.object({
  reasons: z.array(
    z.object({
      code: z.enum(["incremental_profit", "clearance_value", "halo"]),
      amount: z.number(),
    }),
  ),
  value: z.number(),
  best_for_sku_region: z.boolean(),
}) satisfies z.ZodType<Schemas["WhyChosen"]>;

export const bindingConstraintSchema = z.object({
  kind: z.enum([
    "marketing_budget",
    "minimum_margin",
    "margin_floor",
    "max_promoted_skus",
  ]),
  source: z.enum(["brief", "company_policy"]),
  limit: z.number(),
  category: z.string().nullable().optional(),
  region: regionSchema.nullable().optional(),
  evidence: z.enum(["exact", "lower_bound", "unproven"]),
  objective_gain: z.number().nullable(),
}) satisfies z.ZodType<Schemas["BindingConstraint"]>;

export const notSelectedOptionSchema = z.object({
  option: planLineSchema,
  value: z.number(),
  reasons: z.array(
    z.enum([
      "low_uplift",
      "out_of_stock",
      "breaks_policy",
      "over_budget",
      "breaks_margin",
      "max_promoted_skus",
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

export const planRevisionLineSchema = z.object({
  line: planLineSchema,
  expected_units: z.number(),
  promo_cost: z.number(),
  expected_incremental_profit: z.number(),
  why_chosen: whyChosenSchema.nullable().optional(),
  mechanism_comparison: z.array(mechanismOutcomeSchema),
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
}) satisfies z.ZodType<Schemas["PlanningRequest"]>;

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
}) satisfies z.ZodType<Schemas["SessionResponse"]>;

export type Session = z.infer<typeof sessionSchema>;
export type SessionStatus = Session["status"];
export type PlanRevisionLine = z.infer<typeof planRevisionLineSchema>;
export type PlanningRequest = z.infer<typeof planningRequestSchema>;

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
