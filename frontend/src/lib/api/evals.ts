import { z } from "zod";

import { responseReason } from "@/lib/api/reason";
import type { components } from "@/lib/api/schema";

type Schemas = components["schemas"];

// `GET /api/evals/latest` serves `EvalReport` as `make eval` wrote it (ADR 0069).
// The dashboard validates only the fields it reads (ADR 0072); each schema must
// match the OpenAPI-generated type (make api-types), or tsc fails here.
const metricSchema = z.object({
  name: z.string(),
  label: z.string(),
  value: z.number().nullable(),
  count: z.number(),
  of: z.number(),
  target: z.number().nullable().optional(),
  direction: z.enum(["at_least", "at_most"]).nullable().optional(),
  passed: z.boolean().nullable().optional(),
  breakdown: z.record(z.string(), z.number()),
  unit: z.enum(["share", "seconds", "rupees"]),
  aim: z.number().nullable().optional(),
}) satisfies z.ZodType<Schemas["Metric"]>;

const solveStatus = z.enum(["OPTIMAL", "FEASIBLE", "INFEASIBLE"]);

const revisionSchema = z.object({
  number: z.number(),
  lines: z.number(),
  solver_status: solveStatus.nullable(),
}) satisfies z.ZodType<
  Pick<Schemas["RevisionSummary"], "number" | "lines" | "solver_status">
>;

const qualitySchema = z.object({
  objective: z.number(),
  rule_based: z.object({ objective: z.number() }),
  best: z.object({ objective: z.number().nullable() }),
  versus_rule_based: z.enum(["beats", "ties", "loses"]),
  regret: z.number().nullable(),
  regret_rupees: z.number().nullable(),
}) satisfies z.ZodType<{
  objective: number;
  rule_based: Pick<Schemas["RuleBasedSummary"], "objective">;
  best: Pick<Schemas["BestPlanSummary"], "objective">;
  versus_rule_based: Schemas["PlanQuality"]["versus_rule_based"];
  regret: number | null;
  regret_rupees: number | null;
}>;

const runSchema = z.object({
  run: z.number(),
  outcome: z.enum(["planned", "awaiting_clarification", "failed"]),
  passed: z.boolean(),
  error: z.string().nullable().optional(),
  route: z.array(z.string()),
  questions_asked: z.array(z.string()),
  amendments_applied: z.number(),
  fallbacks: z.array(z.string()),
  revision: revisionSchema.nullable().optional(),
  constraints: z.enum(["passed", "failed", "infeasible", "no_plan"]),
  violations: z.array(z.object({ message: z.string() })),
  oracle: z
    .object({
      breaches: z.array(
        z.enum([
          "promo_cost_over_budget",
          "margin_below_minimum",
          "demand_over_stock",
        ]),
      ),
    })
    .nullable()
    .optional(),
  properties: z.array(
    z.object({ property: z.string(), passed: z.boolean(), detail: z.string() }),
  ),
  quality: qualitySchema.nullable().optional(),
  flagged: z.array(z.string()),
  session_s: z.number(),
  usage: z.object({ calls: z.number(), cost_inr: z.number() }),
  cassette_misses: z.array(z.string()),
}) satisfies z.ZodType<
  Pick<
    Schemas["RunResult"],
    | "run"
    | "outcome"
    | "passed"
    | "error"
    | "route"
    | "questions_asked"
    | "amendments_applied"
    | "fallbacks"
    | "constraints"
    | "flagged"
    | "session_s"
    | "cassette_misses"
  > & {
    revision?: Pick<
      Schemas["RevisionSummary"],
      "number" | "lines" | "solver_status"
    > | null;
    violations: Pick<Schemas["Violation"], "message">[];
    oracle?: Pick<Schemas["OracleScore"], "breaches"> | null;
    properties: Schemas["PropertyResult"][];
    usage: Pick<Schemas["SessionUsage"], "calls" | "cost_inr">;
  }
>;

const scenarioSchema = z.object({
  name: z.string(),
  group: z.string(),
  as_of_week: z.number(),
  passed: z.boolean(),
  runs: z.array(runSchema),
}) satisfies z.ZodType<
  Pick<Schemas["ScenarioResult"], "name" | "group" | "as_of_week" | "passed">
>;

export const evalReportSchema = z.object({
  generated_at: z.string(),
  provider: z.string(),
  world_seed: z.number(),
  runs_per_scenario: z.number(),
  planning_settings: z.record(z.string(), z.unknown()),
  metrics: z.array(metricSchema),
  scenarios: z.array(scenarioSchema),
}) satisfies z.ZodType<
  Omit<Schemas["EvalReport"], "scenarios"> & {
    scenarios: Pick<
      Schemas["ScenarioResult"],
      "name" | "group" | "as_of_week" | "passed"
    >[];
  }
>;

export type EvalReport = z.infer<typeof evalReportSchema>;
export type EvalMetric = EvalReport["metrics"][number];
export type EvalScenario = EvalReport["scenarios"][number];
export type EvalRun = EvalScenario["runs"][number];

// Either the report, or the API's reason there is none: no run yet, or a
// `latest.json` this version cannot read (ADR 0069 D9). Both are a 404.
export type LatestEvalReport =
  { kind: "report"; report: EvalReport } | { kind: "none"; detail: string };

// TanStack Query key for the latest report.
export const EVAL_REPORT_QUERY_KEY = ["evals", "latest"];

export class EvalsRequestError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "EvalsRequestError";
  }
}

// Browser-side, through the same-origin `/api/*` proxy (ADR 0018). A 404 is an
// answer, not a failure; anything else that goes wrong throws.
export async function getLatestEvalReport(
  fetchImpl: typeof fetch = fetch,
): Promise<LatestEvalReport> {
  const response = await fetchImpl("/api/evals/latest", { cache: "no-store" });
  if (response.status === 404) {
    return { kind: "none", detail: await responseReason(response) };
  }
  if (!response.ok) throw new EvalsRequestError(await responseReason(response));
  const parsed = evalReportSchema.safeParse(await response.json());
  if (!parsed.success) throw new EvalsRequestError("unexpected eval report");
  return { kind: "report", report: parsed.data };
}
