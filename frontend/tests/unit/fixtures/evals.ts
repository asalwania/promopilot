import { evalReportSchema, type EvalReport } from "@/lib/api/evals";

import recorded from "./eval-report.json";

// The recorded full run of 2026-09-29 (32 scenarios, `make record-eval-cassettes`),
// trimmed to eight scenarios: passing, a failed property, a failed constraint, an
// infeasible revision, a vague brief that asked, an infeasible brief and two regret
// outliers. Every metric is kept as the run wrote it. `diwali-no-budget` gains one
// invented cassette miss, so the run detail has one to show.
export const recordedReport: EvalReport = evalReportSchema.parse(recorded);

export function metric(name: string): EvalReport["metrics"][number] {
  const found = recordedReport.metrics.find((m) => m.name === name);
  if (!found) throw new Error(`no metric ${name} in the fixture`);
  return found;
}

export function scenario(name: string): EvalReport["scenarios"][number] {
  const found = recordedReport.scenarios.find((s) => s.name === name);
  if (!found) throw new Error(`no scenario ${name} in the fixture`);
  return found;
}
