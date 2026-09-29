"use client";

import { useQuery } from "@tanstack/react-query";

import { EvalMetricCards } from "@/components/eval-metric-cards";
import { EvalScenarioTable } from "@/components/eval-scenario-table";
import { RegretChart } from "@/components/regret-chart";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  EVAL_REPORT_QUERY_KEY,
  getLatestEvalReport,
  type EvalReport,
} from "@/lib/api/evals";
import { formatDateTime } from "@/lib/format";

const MAX_RETRIES = 2;

// Reads the latest report once when the page opens (ADR 0072). A 404 is the
// empty state, not an error, and is not retried (ADR 0069 D9).
export function EvalsView() {
  const query = useQuery({
    queryKey: EVAL_REPORT_QUERY_KEY,
    queryFn: () => getLatestEvalReport(),
    retry: MAX_RETRIES,
  });

  if (query.error) {
    return (
      <Notice title="Couldn't load the eval report">
        <CardContent className="flex items-center justify-between gap-4">
          <p className="text-muted-foreground text-sm">{query.error.message}</p>
          <Button
            variant="outline"
            disabled={query.isFetching}
            onClick={() => query.refetch()}
          >
            Retry
          </Button>
        </CardContent>
      </Notice>
    );
  }
  if (!query.data) return <Notice title="Loading the eval report…" />;
  if (query.data.kind === "none") {
    return (
      <Notice title="No eval report yet">
        <CardContent className="flex flex-col gap-2 text-sm">
          <p>{query.data.detail}</p>
          <p className="text-muted-foreground">
            Run <code>make eval</code> for the full suite, or{" "}
            <code>make eval SMOKE=1</code> for the five smoke scenarios. This
            page reads the <code>latest.json</code> it writes to{" "}
            <code>backend/evals/reports/</code> (<code>EVAL_REPORT_DIR</code>).
          </p>
        </CardContent>
      </Notice>
    );
  }
  return <Report report={query.data.report} />;
}

function Report({ report }: { report: EvalReport }) {
  const scenarios = report.scenarios.length;
  const runs = report.runs_per_scenario;
  return (
    <div className="flex w-full flex-col gap-8">
      <div className="flex flex-col gap-2">
        <p
          aria-label="Report provenance"
          className="text-muted-foreground text-sm"
        >
          Generated {formatDateTime(report.generated_at)} · provider{" "}
          <code>{report.provider}</code> · seed-{report.world_seed} world ·{" "}
          {scenarios} {scenarios === 1 ? "scenario" : "scenarios"} × {runs}{" "}
          {runs === 1 ? "run" : "runs"}
        </p>
        <details className="text-sm">
          <summary className="text-muted-foreground cursor-pointer">
            Planning settings
          </summary>
          <dl className="mt-2 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 font-mono text-xs">
            {Object.entries(report.planning_settings).map(([key, value]) => (
              <div key={key} className="contents">
                <dt className="text-muted-foreground">{key}</dt>
                <dd>{String(value)}</dd>
              </div>
            ))}
          </dl>
        </details>
      </div>
      <EvalMetricCards metrics={report.metrics} />
      <Card>
        <CardHeader>
          <CardTitle>Regret distribution</CardTitle>
        </CardHeader>
        <CardContent>
          <RegretChart
            scenarios={report.scenarios}
            regret={report.metrics.find((metric) => metric.name === "regret")}
          />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Scenarios</CardTitle>
        </CardHeader>
        <CardContent>
          <EvalScenarioTable scenarios={report.scenarios} />
        </CardContent>
      </Card>
    </div>
  );
}

function Notice({
  title,
  children,
}: {
  title: string;
  children?: React.ReactNode;
}) {
  return (
    <Card className="w-full">
      <CardHeader>
        <CardTitle role="status">{title}</CardTitle>
      </CardHeader>
      {children}
    </Card>
  );
}
