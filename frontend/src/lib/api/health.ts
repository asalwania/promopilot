import { z } from "zod";

import type { components } from "@/lib/api/schema";

type HealthResponse = components["schemas"]["HealthResponse"];

// Runtime validation for the /health contract; `satisfies` makes tsc fail if the
// OpenAPI-generated type (make api-types) drifts from this schema.
export const healthSchema = z.object({
  status: z.enum(["ok", "degraded"]),
  version: z.string(),
  checks: z.object({
    database: z.enum(["ok", "error"]),
    model_registry: z.enum(["ok", "missing"]),
  }),
  // Replaying the demo recordings, or a live provider (ADR 0073).
  llm: z.object({
    mode: z.enum(["replay", "live"]),
    provider: z.enum(["replay", "openai", "anthropic", "fake"]),
    model: z.string().nullable(),
  }),
}) satisfies z.ZodType<HealthResponse>;

export type Health = z.infer<typeof healthSchema>;
export type LLMStatus = Health["llm"];

export type HealthResult =
  { reachable: true; health: Health } | { reachable: false; reason: string };

// Browser-side: goes through the same-origin `/api/*` proxy (ADR 0001).
export async function getHealth(
  fetchImpl: typeof fetch = fetch,
): Promise<HealthResult> {
  try {
    const response = await fetchImpl("/api/health", { cache: "no-store" });
    if (!response.ok) {
      return { reachable: false, reason: `HTTP ${response.status}` };
    }
    const parsed = healthSchema.safeParse(await response.json());
    if (!parsed.success) {
      return { reachable: false, reason: "unexpected /health response" };
    }
    return { reachable: true, health: parsed.data };
  } catch (error) {
    return {
      reachable: false,
      reason: error instanceof Error ? error.message : String(error),
    };
  }
}
