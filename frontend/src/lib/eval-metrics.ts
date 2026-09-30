import type { EvalMetric } from "@/lib/api/evals";
import { formatDuration, formatPrice, formatShare } from "@/lib/format";

// The dashboard's metric groups, in order (ADR 0072). A metric the report adds
// later still shows, under "Other".
const GROUPS: { title: string; names: string[] }[] = [
  {
    title: "Constraints",
    names: ["constraint_satisfaction", "oracle_breach_rate"],
  },
  {
    title: "Agent behaviour",
    names: [
      "extraction_accuracy",
      "clarification_behaviour",
      "infeasibility_handling",
      "grounding",
    ],
  },
  {
    title: "Plan quality",
    names: ["plan_quality", "regret", "consistency", "open_issues"],
  },
  {
    title: "Model recovery",
    names: [
      "elasticity_recovery",
      "substitute_precision",
      "substitute_recall",
      "complement_precision",
      "complement_recall",
      "baseline_wape",
      "baseline_wape_store_sku",
      "baseline_wape_region_sku",
    ],
  },
  {
    title: "Latency and cost",
    names: ["session_latency_p50", "session_cost_p50"],
  },
];
const OTHER = "Other";

export type MetricGroup = { title: string; metrics: EvalMetric[] };

// The non-empty groups in order, each metric in report order within its group.
export function groupMetrics(metrics: EvalMetric[]): MetricGroup[] {
  const titleOf = (name: string) =>
    GROUPS.find((group) => group.names.includes(name))?.title ?? OTHER;
  return [...GROUPS.map((group) => group.title), OTHER]
    .map((title) => ({
      title,
      metrics: metrics.filter((metric) => titleOf(metric.name) === title),
    }))
    .filter((group) => group.metrics.length > 0);
}

export type MetricStatus = "pass" | "fail" | "reported" | "not_scored";

// Read from the report as it is: the dashboard never judges a metric itself.
export function metricStatus(metric: EvalMetric): MetricStatus {
  if (metric.value === null) return "not_scored";
  if (metric.passed === true) return "pass";
  if (metric.passed === false) return "fail";
  return "reported";
}

// An amount in the metric's unit: a share as a signed percentage, a P50 in
// seconds as a duration, rupees with their paise (a session costs a few), and a
// median count as a plain number.
export function formatMetricAmount(metric: EvalMetric, amount: number): string {
  if (metric.unit === "count") return String(amount);
  if (metric.unit === "seconds") return formatDuration(amount * 1000);
  if (metric.unit === "rupees") return formatPrice(amount);
  return formatShare(amount);
}

const SIGNS = { at_least: "≥", at_most: "≤" } as const;

// "Target ≥ 95%", "Report · aim ≤ 25%" or "Report".
export function formatTarget(metric: EvalMetric): string {
  const sign = SIGNS[metric.direction ?? "at_least"];
  if (metric.target != null) {
    return `Target ${sign} ${formatMetricAmount(metric, metric.target)}`;
  }
  if (metric.aim != null) {
    return `Report · aim ${sign} ${formatMetricAmount(metric, metric.aim)}`;
  }
  return "Report";
}

// The dashboard's source for every eval number (SPEC §11 UX rule, ADR 0072).
export function evalSource(name: string): string {
  return `make eval · ${name}`;
}

// A breakdown or report key for reading, e.g. `promo_cost_over_budget`.
export function humanise(key: string): string {
  return key.replaceAll("_", " ");
}

const SCENARIO_GROUPS: Record<string, string> = {
  standard_festive: "Standard festive",
  tight_budget: "Tight budget",
  overstock_clearance: "Overstock clearance",
  competitor_price_war: "Competitor price war",
  regional_holidays: "Regional holidays",
  heavy_cannibalisation: "Heavy cannibalisation",
  vague_or_conflicting: "Vague or conflicting",
  infeasible_constraints: "Infeasible constraints",
  mid_plan_amendments: "Mid-plan amendments",
};

// The SPEC §12.1 group name for a scenario group's slug.
export function scenarioGroupLabel(group: string): string {
  return SCENARIO_GROUPS[group] ?? humanise(group);
}
