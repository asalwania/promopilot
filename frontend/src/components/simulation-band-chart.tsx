"use client";

import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { SOURCES } from "@/lib/sources";

export type BandPoint = {
  label: string;
  range: { p10: number; p50: number; p90: number };
};

const HEIGHT = 300;
const BAND = "var(--color-chart-2)";
const MEDIAN = "var(--color-foreground)";

// A P10–P90 band with the P50 line through it, one point per plan line (F-09,
// SPEC §11). It only draws what the simulator returned (ADR 0068 D1); the panel's
// "Show values" table carries the same numbers for reading and for tests.
export function SimulationBandChart({
  title,
  points,
  format,
}: {
  title: string;
  points: BandPoint[];
  format: (value: number) => string;
}) {
  const data = points.map(({ label, range }) => ({
    label,
    band: [range.p10, range.p90],
    p50: range.p50,
    range,
  }));
  return (
    <figure aria-label={title} className="flex flex-col gap-2">
      <figcaption className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <span className="font-medium">{title}</span>
        <ul aria-label="Legend" className="flex gap-4 text-xs">
          <li className="flex items-center gap-1.5">
            <span
              aria-hidden
              className="inline-block h-3 w-4 rounded-sm opacity-40"
              style={{ background: BAND }}
            />
            P10–P90 band
          </li>
          <li className="flex items-center gap-1.5">
            <span
              aria-hidden
              className="inline-block h-0.5 w-4"
              style={{ background: MEDIAN }}
            />
            P50
          </li>
        </ul>
      </figcaption>
      <div aria-hidden>
        <ResponsiveContainer
          width="100%"
          height={HEIGHT}
          initialDimension={{ width: 800, height: HEIGHT }}
        >
          <ComposedChart
            data={data}
            margin={{ top: 8, right: 16, bottom: 8, left: 8 }}
          >
            <CartesianGrid strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="label"
              interval={data.length > 16 ? "preserveStartEnd" : 0}
              angle={-30}
              textAnchor="end"
              height={72}
              tick={{ fontSize: 11 }}
            />
            <YAxis
              tickFormatter={(value: number) => format(value)}
              width={88}
              tick={{ fontSize: 11 }}
            />
            <Tooltip
              content={({ active, payload }) => {
                const point = payload?.[0]?.payload as
                  (typeof data)[number] | undefined;
                if (!active || !point) return null;
                return (
                  <div className="bg-popover text-popover-foreground rounded-md border p-2 text-xs shadow">
                    <div className="font-mono font-medium">{point.label}</div>
                    <div>
                      P10 {format(point.range.p10)} · P50{" "}
                      {format(point.range.p50)} · P90 {format(point.range.p90)}
                    </div>
                    <div className="text-muted-foreground">
                      Source: {SOURCES.simulation}
                    </div>
                  </div>
                );
              }}
            />
            <Area
              dataKey="band"
              name="P10–P90 band"
              stroke="none"
              fill={BAND}
              fillOpacity={0.35}
              isAnimationActive={false}
            />
            <Line
              dataKey="p50"
              name="P50"
              stroke={MEDIAN}
              strokeWidth={2}
              dot={{ r: 2 }}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}
