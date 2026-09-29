import { SourcedNumber } from "@/components/sourced-number";
import { Badge } from "@/components/ui/badge";
import type { EvalMetric } from "@/lib/api/evals";
import {
  evalSource,
  formatMetricAmount,
  formatTarget,
  groupMetrics,
  humanise,
  metricStatus,
  type MetricStatus,
} from "@/lib/eval-metrics";
import { cn } from "@/lib/utils";

const STATUS: Record<MetricStatus, { label: string; className: string }> = {
  pass: {
    label: "Pass",
    className:
      "bg-emerald-600/10 text-emerald-700 dark:bg-emerald-400/10 dark:text-emerald-400",
  },
  fail: { label: "Fail", className: "bg-destructive/10 text-destructive" },
  reported: { label: "Reported", className: "bg-secondary text-foreground" },
  not_scored: {
    label: "Not scored",
    className: "bg-muted text-muted-foreground",
  },
};

// Every SPEC §12.2 metric against its target, grouped (ADR 0072). Each badge is
// the report's own `passed`: the dashboard never judges a metric itself.
export function EvalMetricCards({ metrics }: { metrics: EvalMetric[] }) {
  const judged = metrics.filter((metric) => metric.passed != null);
  const met = judged.filter((metric) => metric.passed === true);
  return (
    <div className="flex flex-col gap-6">
      <p className="text-sm font-medium">
        {met.length} of {judged.length} targets met
      </p>
      {groupMetrics(metrics).map((group) => (
        <section
          key={group.title}
          aria-label={group.title}
          className="flex flex-col gap-3"
        >
          <h2 className="text-muted-foreground text-sm font-medium tracking-wide uppercase">
            {group.title}
          </h2>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {group.metrics.map((metric) => (
              <MetricCard key={metric.name} metric={metric} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function MetricCard({ metric }: { metric: EvalMetric }) {
  const status = STATUS[metricStatus(metric)];
  const counted = metric.of > 0 ? `${metric.count} of ${metric.of}` : undefined;
  const breakdown = Object.entries(metric.breakdown);
  return (
    <article
      aria-label={metric.label}
      className="bg-card text-card-foreground flex flex-col gap-2 rounded-lg border p-4"
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-sm leading-snug font-medium">{metric.label}</h3>
        <Badge className={cn("shrink-0", status.className)}>
          {status.label}
        </Badge>
      </div>
      <p className="text-2xl font-semibold">
        {metric.value === null ? (
          <span className="text-muted-foreground">n/a</span>
        ) : (
          <SourcedNumber
            value={metric.value}
            format={(value) => formatMetricAmount(metric, value)}
            source={evalSource(metric.name)}
            detail={counted}
          />
        )}
      </p>
      <div className="text-muted-foreground flex flex-wrap justify-between gap-x-3 text-xs">
        <span>{formatTarget(metric)}</span>
        {counted && <span>{counted}</span>}
      </div>
      {breakdown.length > 0 && (
        <ul
          aria-label="Breakdown"
          className="text-muted-foreground flex flex-wrap gap-1 text-xs"
        >
          {breakdown.map(([key, count]) => (
            <li key={key} className="bg-muted rounded px-1.5 py-0.5">
              {humanise(key)} {count}
            </li>
          ))}
        </ul>
      )}
    </article>
  );
}
