"use client";

import { LoaderCircle } from "lucide-react";
import { useId, useState, type FormEvent } from "react";

import { type ActionOutcome } from "@/components/amend-box";
import { ErrorMessage, type ShownError } from "@/components/error-message";
import { SimulationBandChart } from "@/components/simulation-band-chart";
import { SourcedNumber } from "@/components/sourced-number";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import type { PlanSimulation, Region } from "@/lib/api/sessions";
import {
  formatMoney,
  formatRupees,
  formatShare,
  formatTokens,
} from "@/lib/format";
import { SOURCES } from "@/lib/sources";

type Outcomes = PlanSimulation["total"];
type Percentiles = Outcomes["units"];

// Re-simulates the latest plan revision, the competitor matching each line's
// discount at this probability, or never reacting when null (ADR 0045, ADR 0068).
export type Simulate = (
  matchProbability: number | null,
) => Promise<ActionOutcome>;

// What the chart can show: the metric, how it reads and its exact form for tooltips.
export type SimulatedMetric = {
  key: "gross_profit" | "units" | "promo_spend";
  label: string;
  format: (value: number) => string;
  exact: (value: number) => string;
};

const METRICS: SimulatedMetric[] = [
  {
    key: "gross_profit",
    label: "Gross profit",
    format: formatMoney,
    exact: formatRupees,
  },
  { key: "units", label: "Units", format: formatTokens, exact: formatTokens },
  {
    key: "promo_spend",
    label: "Promo spend",
    format: formatMoney,
    exact: formatRupees,
  },
];

const REGION_ORDER: Region[] = ["North", "South", "East", "West"];
const ALL = "all";

// The Monte Carlo simulation of the plan revision on screen (F-09, SPEC §11): each
// plan line's P10–P90 band and P50, the plan's totals, and a stress test against a
// competitor reaction. Every number is the simulator's (ADR 0042, ADR 0068).
export function SimulationPanel({
  revisionNumber,
  simulation,
  onSimulate,
}: {
  revisionNumber: number;
  simulation: PlanSimulation | null | undefined;
  // Absent where the plan can't be re-simulated, e.g. once it is final (ADR 0066).
  onSimulate?: Simulate;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Simulation</CardTitle>
        {simulation && (
          <p className="text-muted-foreground text-sm">
            <span className="text-foreground font-medium">
              {reactionLabel(simulation)}
            </span>{" "}
            · {simulation.n_runs} runs, seed {simulation.seed}
          </p>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {simulation ? (
          <SimulatedPlan simulation={simulation} />
        ) : (
          <p className="text-muted-foreground text-sm">
            Plan revision {revisionNumber} has no simulation yet.
          </p>
        )}
        {onSimulate && <ResimulateForm onSimulate={onSimulate} />}
      </CardContent>
    </Card>
  );
}

// The stored simulation names its competitor reaction (ADR 0045 D6).
export function reactionLabel(simulation: PlanSimulation): string {
  const reaction = simulation.competitor_reaction;
  return reaction
    ? `Stress test: the competitor matches each plan line's discount with probability ${formatShare(reaction.match_probability)}`
    : "No competitor reaction";
}

function SimulatedPlan({ simulation }: { simulation: PlanSimulation }) {
  const [metricKey, setMetricKey] = useState<SimulatedMetric["key"]>(
    METRICS[0].key,
  );
  const [region, setRegion] = useState<Region | typeof ALL>(ALL);
  const [showValues, setShowValues] = useState(false);
  const metric = METRICS.find((m) => m.key === metricKey) ?? METRICS[0];
  const regions = REGION_ORDER.filter((r) =>
    simulation.lines.some((line) => line.region === r),
  );
  const lines = simulation.lines.filter(
    (line) => region === ALL || line.region === region,
  );
  const points = lines.map((line) => ({
    label: `${line.sku_id} · ${line.region}`,
    range: line[metric.key],
  }));
  const runs = `of ${simulation.n_runs} runs (seed ${simulation.seed})`;
  const detail = (name: string, value: number) =>
    `${metric.label.toLowerCase()}, ${name} ${runs}: ${metric.exact(value)}`;

  return (
    <>
      <PlanTotals simulation={simulation} runs={runs} />
      <div className="flex flex-wrap items-center gap-4">
        <ToggleGroup
          label="Metric"
          options={METRICS.map((m) => ({ value: m.key, label: m.label }))}
          value={metricKey}
          onChange={setMetricKey}
        />
        {regions.length > 1 && (
          <ToggleGroup
            label="Regions"
            options={[
              { value: ALL, label: "All regions" },
              ...regions.map((r) => ({ value: r, label: r })),
            ]}
            value={region}
            onChange={setRegion}
          />
        )}
      </div>
      <SimulationBandChart
        title={`Simulated ${metric.label.toLowerCase()} by plan line`}
        points={points}
        format={metric.format}
      />
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
        <table aria-label="Simulated ranges" className="w-full text-sm">
          <thead>
            <tr className="border-b">
              {["Plan line", "P10", "P50", "P90"].map((column) => (
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
            {points.map(({ label, range }) => (
              <tr key={label} className="border-b">
                <td className="px-2 py-2 font-mono">{label}</td>
                {(["p10", "p50", "p90"] as const).map((name) => (
                  <td key={name} className="px-2 py-2 tabular-nums">
                    <SourcedNumber
                      value={range[name]}
                      format={metric.format}
                      source={SOURCES.simulation}
                      detail={detail(name.toUpperCase(), range[name])}
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

// The whole plan's ranges are percentiles of each run's sums, not sums of line
// percentiles (ADR 0042), so they come from `total`, never from adding lines up.
function PlanTotals({
  simulation,
  runs,
}: {
  simulation: PlanSimulation;
  runs: string;
}) {
  const { total } = simulation;
  const money = { format: formatMoney, exact: formatRupees };
  const share = { format: formatShare, exact: formatShare };
  const units = { format: formatTokens, exact: formatTokens };
  const tiles: Array<{
    label: string;
    range: Percentiles | null | undefined;
    as: { format: (n: number) => string; exact: (n: number) => string };
  }> = [
    { label: "Gross profit", range: total.gross_profit, as: money },
    { label: "Units", range: total.units, as: units },
    { label: "Revenue", range: total.revenue, as: money },
    { label: "Promo spend", range: total.promo_spend, as: money },
    { label: "Margin", range: total.margin, as: share },
    { label: "Sell-through", range: total.sell_through, as: share },
  ];
  const sourced = (
    label: string,
    name: "P10" | "P50" | "P90",
    value: number,
    as: (typeof tiles)[number]["as"],
  ) => (
    <SourcedNumber
      value={value}
      format={as.format}
      source={SOURCES.simulation}
      detail={`${label.toLowerCase()}, ${name} ${runs}: ${as.exact(value)}`}
    />
  );
  return (
    <section
      aria-label="Plan totals"
      className="grid grid-cols-2 gap-3 text-sm lg:grid-cols-4"
    >
      {tiles.map(({ label, range, as }) =>
        range ? (
          <div key={label} className="rounded-lg border p-3">
            <div className="text-muted-foreground">{label}</div>
            <div className="text-lg font-medium">
              {sourced(label, "P50", range.p50, as)}
            </div>
            <div className="text-muted-foreground text-xs">
              P10 {sourced(label, "P10", range.p10, as)} – P90{" "}
              {sourced(label, "P90", range.p90, as)}
            </div>
          </div>
        ) : null,
      )}
      {simulation.regions.map(({ region, stockout_probability }) => (
        <div key={region} className="rounded-lg border p-3">
          <div className="text-muted-foreground">
            Stock-out risk in {region}
          </div>
          <div className="text-lg font-medium">
            <SourcedNumber
              value={stockout_probability}
              format={formatShare}
              source={SOURCES.simulation}
              detail={`share of ${simulation.n_runs} runs in which a ${region} plan line ran out`}
            />
          </div>
        </div>
      ))}
    </section>
  );
}

function ToggleGroup<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: Array<{ value: T; label: string }>;
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-1">
      {options.map((option) => (
        <Button
          key={option.value}
          size="sm"
          variant={option.value === value ? "secondary" : "ghost"}
          aria-pressed={option.value === value}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </Button>
      ))}
    </div>
  );
}

// The match probabilities offered, as the API takes them (ADR 0068 D3).
const REACTIONS = [
  { value: "none", label: "No reaction", probability: null },
  { value: "0.25", label: "25%", probability: 0.25 },
  { value: "0.5", label: "50%", probability: 0.5 },
  { value: "1", label: "100%", probability: 1 },
] as const;

function ResimulateForm({ onSimulate }: { onSimulate: Simulate }) {
  const id = useId();
  const [choice, setChoice] = useState<string>("0.5");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<ShownError | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const reaction = REACTIONS.find((r) => r.value === choice) ?? REACTIONS[0];
    setSending(true);
    setError(null);
    const result = await onSimulate(reaction.probability);
    setSending(false);
    if (!result.ok) {
      setError({
        message: `Couldn't re-simulate: ${result.reason}`,
        referenceId: result.referenceId,
      });
    }
  }

  return (
    <form
      aria-label="Stress-test with competitor reaction"
      onSubmit={submit}
      className="flex flex-col gap-2 border-t pt-4"
    >
      <p className="text-sm font-medium">
        Stress-test with competitor reaction
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={id}>Competitor match probability</Label>
          <select
            id={id}
            value={choice}
            disabled={sending}
            onChange={(event) => setChoice(event.target.value)}
            className="border-input bg-background h-9 rounded-md border px-3 text-sm"
          >
            {REACTIONS.map((reaction) => (
              <option key={reaction.value} value={reaction.value}>
                {reaction.label}
              </option>
            ))}
          </select>
        </div>
        <Button type="submit" disabled={sending}>
          {sending && (
            <LoaderCircle aria-hidden className="size-4 animate-spin" />
          )}
          {sending ? "Re-simulating…" : "Re-simulate"}
        </Button>
      </div>
      <p className="text-muted-foreground text-xs">
        The result replaces the stored simulation, and the plan table&apos;s
        ranges with it. Choose &ldquo;No reaction&rdquo; to go back to the plain
        simulation.
      </p>
      {error && (
        <ErrorMessage message={error.message} referenceId={error.referenceId} />
      )}
    </form>
  );
}
