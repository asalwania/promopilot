import type { components } from "@/lib/api/schema";

import { SESSION_ID } from "./sessions";

type TraceEvent = components["schemas"]["TraceEvent"];
type TracePayload = components["schemas"]["TracePayload"];

const START = Date.parse("2026-09-28T10:00:00Z");

export function traceEvent(
  id: number,
  node: string | null,
  payload: TracePayload,
): TraceEvent {
  return {
    id,
    session_id: SESSION_ID,
    at: new Date(START + id * 1000).toISOString(),
    node,
    payload,
  };
}

// One of every payload kind, in the order a planning round emits them (ADR 0047).
export const traceEvents: TraceEvent[] = [
  traceEvent(1, "context", { kind: "node_started" }),
  traceEvent(2, "context", {
    kind: "token_usage",
    model: "gpt-4.1-mini",
    input_tokens: 12_345,
    output_tokens: 678,
    cost_usd: 0.006,
    cost_inr: 0.58,
  }),
  traceEvent(3, "context", {
    kind: "clarification",
    questions: ["What is the marketing budget?"],
  }),
  traceEvent(4, "context", {
    kind: "node_finished",
    outcome: "completed",
    duration_ms: 1250,
    error: null,
  }),
  traceEvent(5, "planner", { kind: "node_started" }),
  traceEvent(6, "planner", {
    kind: "tool_called",
    tool: "get_inventory_status",
    arguments: { regions: ["North"] },
    ok: true,
    error_code: null,
    result_summary: { items: "<12 items>" },
  }),
  traceEvent(7, "planner", {
    kind: "tool_called",
    tool: "run_optimizer",
    arguments: { candidate_set_id: "abc" },
    ok: false,
    error_code: "unknown_candidate_set",
    result_summary: "No candidate set abc",
  }),
  traceEvent(8, "planner", {
    kind: "token_usage",
    model: "local-model",
    input_tokens: 2000,
    output_tokens: 100,
    cost_usd: null,
    cost_inr: null,
  }),
  traceEvent(9, "planner", {
    kind: "node_finished",
    outcome: "completed",
    duration_ms: 42_000,
    error: null,
  }),
  traceEvent(10, "critic", { kind: "node_started" }),
  traceEvent(11, "critic", {
    kind: "finding",
    source: "plan_validation",
    code: "BUDGET",
    message: "Promo cost ₹2,10,000 is over the ₹2,00,000 budget.",
  }),
  traceEvent(12, "critic", {
    kind: "decision",
    decision: "open_issues",
    summary: "The plan has 1 open issue; the planner tries again.",
  }),
  traceEvent(13, "critic", {
    kind: "node_finished",
    outcome: "completed",
    duration_ms: 300,
    error: null,
  }),
  traceEvent(14, "planner", { kind: "node_started" }),
  traceEvent(15, "planner", {
    kind: "node_finished",
    outcome: "failed",
    duration_ms: 900,
    error: "Optimiser crashed",
  }),
  traceEvent(16, "approval", { kind: "node_started" }),
  traceEvent(17, "approval", {
    kind: "node_finished",
    outcome: "interrupted",
    duration_ms: 5,
    error: null,
  }),
  traceEvent(18, "explainer", { kind: "node_started" }),
];
