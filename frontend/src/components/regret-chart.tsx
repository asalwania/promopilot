"use client";

import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { SourcedNumber } from "@/components/sourced-number";
import { Button } from "@/components/ui/button";
import type { EvalMetric, EvalScenario } from "@/lib/api/evals";
import { evalSource, formatTarget } from "@/lib/eval-metrics";
import { formatShare } from "@/lib/format";

const TITLE = "Regret against the best plan, per scored run";
const HEIGHT = 280;
// Regret is signed and unbounded (ADR 0063): one outlier would flatten every
// other bar, so the axis stops at ±100% and a bar past it is drawn at the edge.
const LIMIT = 1;
const BAR = "var(--color-chart-2)";
const CLIPPED = "var(--color-chart-4)";
const MEDIAN = "var(--color-foreground)";
const TARGET = "var(--color-muted-foreground)";

type Point = { label: string; regret: number; shown: number; clipped: boolean };

// One bar per scored run, lowest regret first, with the report's median and
// the SPEC §12.2 target marked (ADR 0072). It sorts and clips for drawing only;
// every value is the report's, and "Show values" lists them for reading.
export function RegretChart({
  scenarios,
  regret,
}: {
  scenarios: EvalScenario[];
  regret: EvalMetric | undefined;
}) {
  const [showValues, setShowValues] = useState(false);
  const runs = scenarios.flatMap((scenario) =>
    scenario.runs.map((run) => ({
      label:
        scenario.runs.length > 1
          ? `${scenario.name} · run ${run.run}`
          : scenario.name,
      regret: run.quality?.regret ?? null,
    })),
  );
  const points: Point[] = runs
    .filter(
      (run): run is { label: string; regret: number } => run.regret !== null,
    )
    .sort((a, b) => a.regret - b.regret)
    .map(({ label, regret: value }) => ({
      label,
      regret: value,
      shown: Math.max(-LIMIT, Math.min(LIMIT, value)),
      clipped: Math.abs(value) > LIMIT,
    }));
  const missing = runs.length - points.length;

  if (points.length === 0) {
    return (
      <p className="text-muted-foreground text-sm">
        No run has a regret to show.
      </p>
    );
  }

  const median = regret?.value ?? null;
  const target = regret?.target ?? null;
  return (
    <div className="flex flex-col gap-3">
      <figure aria-label={TITLE} className="flex flex-col gap-2">
        <figcaption className="flex flex-wrap items-center justify-between gap-2 text-sm">
          <span className="font-medium">{TITLE}</span>
          <ul aria-label="Legend" className="flex flex-wrap gap-4 text-xs">
            {median !== null && (
              <li className="flex items-center gap-1.5">
                <span
                  aria-hidden
                  className="inline-block h-0.5 w-4"
                  style={{ background: MEDIAN }}
                />
                Median {formatShare(median)}
              </li>
            )}
            {regret && target !== null && (
              <li className="flex items-center gap-1.5">
                <span
                  aria-hidden
                  className="inline-block w-4 border-t-2 border-dashed"
                  style={{ borderColor: TARGET }}
                />
                {formatTarget(regret)}
              </li>
            )}
            {points.some((point) => point.clipped) && (
              <li className="flex items-center gap-1.5">
                <span
                  aria-hidden
                  className="inline-block h-3 w-3 rounded-sm"
                  style={{ background: CLIPPED }}
                />
                Beyond ±100%, drawn at the edge
              </li>
            )}
          </ul>
        </figcaption>
        <div aria-hidden>
          <ResponsiveContainer
            width="100%"
            height={HEIGHT}
            initialDimension={{ width: 800, height: HEIGHT }}
          >
            <BarChart
              data={points}
              margin={{ top: 8, right: 16, bottom: 8, left: 8 }}
            >
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis
                dataKey="label"
                interval={points.length > 16 ? "preserveStartEnd" : 0}
                angle={-30}
                textAnchor="end"
                height={96}
                tick={{ fontSize: 11 }}
              />
              <YAxis
                domain={[-LIMIT, LIMIT]}
                ticks={[-1, -0.5, 0, 0.5, 1]}
                tickFormatter={(value: number) => formatShare(value)}
                width={56}
                tick={{ fontSize: 11 }}
              />
              <Tooltip
                cursor={{ fillOpacity: 0.1 }}
                content={({ active, payload }) => {
                  const point = payload?.[0]?.payload as Point | undefined;
                  if (!active || !point) return null;
                  return (
                    <div className="bg-popover text-popover-foreground rounded-md border p-2 text-xs shadow">
                      <div className="font-mono font-medium">{point.label}</div>
                      <div>
                        Regret {formatShare(point.regret)}
                        {point.clipped && " (beyond the axis)"}
                      </div>
                      <div className="text-muted-foreground">
                        Source: {evalSource("regret")}
                      </div>
                    </div>
                  );
                }}
              />
              <ReferenceLine y={0} stroke="var(--color-border)" />
              {median !== null && (
                <ReferenceLine
                  y={Math.max(-LIMIT, Math.min(LIMIT, median))}
                  stroke={MEDIAN}
                  strokeWidth={2}
                />
              )}
              {target !== null && (
                <ReferenceLine
                  y={target}
                  stroke={TARGET}
                  strokeWidth={2}
                  strokeDasharray="6 4"
                />
              )}
              <Bar
                dataKey="shown"
                name="Regret"
                radius={4}
                maxBarSize={32}
                isAnimationActive={false}
              >
                {points.map((point) => (
                  <Cell
                    key={point.label}
                    fill={point.clipped ? CLIPPED : BAR}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </figure>
      {missing > 0 && (
        <p className="text-muted-foreground text-sm">
          {missing} {missing === 1 ? "run has" : "runs have"} no regret: no
          scored plan, or the best plan is infeasible.
        </p>
      )}
      <div>
        <Button
          variant="outline"
          size="sm"
          aria-expanded={showValues}
          onClick={() => setShowValues(!showValues)}
        >
          {showValues ? "Hide values" : "Show values"}
        </Button>
      </div>
      {showValues && (
        <table aria-label="Regret per run" className="w-full text-sm">
          <thead>
            <tr className="border-b">
              {["Run", "Regret", "Chart"].map((column) => (
                <th
                  key={column}
                  scope="col"
                  className="text-muted-foreground px-2 py-2 text-left font-medium"
                >
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {points.map((point) => (
              <tr key={point.label} className="border-b">
                <td className="px-2 py-2 font-mono">{point.label}</td>
                <td className="px-2 py-2 tabular-nums">
                  <SourcedNumber
                    value={point.regret}
                    format={formatShare}
                    source={evalSource("regret")}
                    detail="against the best plan on true parameters"
                  />
                </td>
                <td className="text-muted-foreground px-2 py-2">
                  {point.clipped ? "Beyond the axis" : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
