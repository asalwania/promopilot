import { z } from "zod";

import type { components } from "@/lib/api/schema";

type Schemas = components["schemas"];

// Runtime validation for the session's SSE trace stream (ADR 0047); `satisfies`
// makes tsc fail if the OpenAPI-generated types drift from these schemas.
const tracePayloadSchema = z.discriminatedUnion("kind", [
  z.object({ kind: z.literal("node_started") }) satisfies z.ZodType<
    Schemas["NodeStarted"]
  >,
  z.object({
    kind: z.literal("node_finished"),
    outcome: z.enum(["completed", "interrupted", "failed"]),
    duration_ms: z.number(),
    error: z.string().nullable().optional(),
  }) satisfies z.ZodType<Schemas["NodeFinished"]>,
  z.object({
    kind: z.literal("tool_called"),
    tool: z.string(),
    arguments: z.unknown(),
    ok: z.boolean(),
    error_code: z.string().nullable().optional(),
    result_summary: z.unknown(),
  }) satisfies z.ZodType<Schemas["ToolCalled"]>,
  z.object({
    kind: z.literal("decision"),
    decision: z.string(),
    summary: z.string(),
  }) satisfies z.ZodType<Schemas["DecisionMade"]>,
  z.object({
    kind: z.literal("clarification"),
    questions: z.array(z.string()),
  }) satisfies z.ZodType<Schemas["ClarificationAsked"]>,
  z.object({
    kind: z.literal("finding"),
    source: z.string(),
    code: z.string(),
    message: z.string(),
  }) satisfies z.ZodType<Schemas["FindingRaised"]>,
  z.object({
    kind: z.literal("token_usage"),
    model: z.string(),
    input_tokens: z.number(),
    output_tokens: z.number(),
    cost_usd: z.number().nullable(),
    cost_inr: z.number().nullable(),
  }) satisfies z.ZodType<Schemas["TokensUsed"]>,
]);

export const traceEventSchema = z.object({
  id: z.number(),
  session_id: z.string(),
  at: z.string(),
  node: z.string().nullable(),
  payload: tracePayloadSchema,
}) satisfies z.ZodType<Schemas["TraceEvent"]>;

export type TraceEvent = z.infer<typeof traceEventSchema>;
export type TracePayload = TraceEvent["payload"];
