"use client";

import { ChevronDown, ChevronRight } from "lucide-react";
import { Fragment, useState } from "react";

import {
  CannibalisationCallout,
  HaloCallout,
} from "@/components/cross-effect-callouts";
import { MechanismDrawer } from "@/components/mechanism-drawer";
import { SourcedNumber } from "@/components/sourced-number";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { UndercutCallout } from "@/components/undercut-callout";
import type { CompetitorGap } from "@/lib/api/catalog";
import type { LineSimulation, PlanRevisionLine } from "@/lib/api/sessions";
import {
  formatMechanism,
  formatMoney,
  formatRupees,
  formatShare,
  formatTokens,
  formatUplift,
  formatWeek,
} from "@/lib/format";
import { SOURCES } from "@/lib/sources";
import { cn } from "@/lib/utils";

// One plan line with what the other tools said about it: its simulated ranges,
// the Explainer's rationale and a competitor undercut on its SKU and region.
export type PlanRow = {
  planned: PlanRevisionLine;
  simulated?: LineSimulation;
  rationale?: string;
  undercut?: CompetitorGap;
};

export type SimulationRuns = { n_runs: number; seed: number };

const COLUMNS = [
  "SKU",
  "Mechanism",
  "Depth",
  "Start",
  "Duration",
  "Target segment",
  "Uplift",
  "Profit P10–P90",
  "Stock-out risk",
  "Promo cost",
  "Expected incremental profit",
  "Notes",
  "Details",
];
const NUMERIC = new Set([
  "Uplift",
  "Profit P10–P90",
  "Stock-out risk",
  "Promo cost",
  "Expected incremental profit",
]);

// Effects under 1% of a SKU's units are noise to a manager (ADR 0033).
const MIN_EFFECT_PCT = 1;

// One region's plan lines in plan order (ADR 0060): every number names its tool.
export function PlanTable({
  region,
  rows,
  runs,
}: {
  region: string;
  rows: PlanRow[];
  runs?: SimulationRuns | null;
}) {
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  const toggle = (key: string) =>
    setOpen((current) => {
      const next = new Set(current);
      if (!next.delete(key)) next.add(key);
      return next;
    });

  return (
    <table aria-label={`Plan lines in ${region}`} className="w-full text-sm">
      <thead>
        <tr className="border-b">
          {COLUMNS.map((column) => (
            <th
              key={column}
              scope="col"
              className={cn(
                "text-muted-foreground px-2 py-2 font-medium",
                NUMERIC.has(column) ? "text-right" : "text-left",
              )}
            >
              {column}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => {
          const { line } = row.planned;
          const key = `${line.sku_id}-${line.region}`;
          const expanded = open.has(key);
          return (
            <Fragment key={key}>
              <PlanLineRow
                row={row}
                runs={runs}
                expanded={expanded}
                onToggle={() => toggle(key)}
              />
              {expanded && (
                <tr className="bg-muted/30 border-b">
                  <td colSpan={COLUMNS.length} className="px-4 py-3">
                    <PlanLineDetails row={row} />
                  </td>
                </tr>
              )}
            </Fragment>
          );
        })}
      </tbody>
    </table>
  );
}

function PlanLineRow({
  row,
  runs,
  expanded,
  onToggle,
}: {
  row: PlanRow;
  runs?: SimulationRuns | null;
  expanded: boolean;
  onToggle: () => void;
}) {
  const { planned, simulated } = row;
  const { line } = planned;
  const label = `${line.sku_id} in ${line.region}`;
  const Chevron = expanded ? ChevronDown : ChevronRight;
  return (
    <tr className="border-b">
      <td className="px-2 py-2 font-mono">{line.sku_id}</td>
      <td className="px-2 py-2">
        {formatMechanism(line.mechanism)}
        {line.bundle_partner_sku_id && (
          <span className="text-muted-foreground font-mono">
            {" "}
            + {line.bundle_partner_sku_id}
          </span>
        )}
      </td>
      <td className="px-2 py-2">
        <Decision value={line.depth_pct} format={(n) => `${n}%`} />
      </td>
      <td className="px-2 py-2">
        <Decision value={line.start_week} format={formatWeek} />
      </td>
      <td className="px-2 py-2">
        <Decision value={line.duration_weeks} format={(n) => `${n} wk`} />
      </td>
      <td className="px-2 py-2">{line.target_segment}</td>
      <NumberCell>
        {planned.uplift_pct != null && planned.baseline_units != null ? (
          <SourcedNumber
            value={planned.uplift_pct}
            format={formatUplift}
            source={SOURCES.lineEstimate}
            detail={`${formatTokens(planned.expected_units)} units against a baseline of ${formatTokens(planned.baseline_units)} over the promo weeks`}
          />
        ) : (
          <Missing />
        )}
      </NumberCell>
      <NumberCell>
        {simulated ? (
          <ProfitRange simulated={simulated} runs={runs} />
        ) : (
          <Missing />
        )}
      </NumberCell>
      <NumberCell>
        {simulated ? (
          <SourcedNumber
            value={simulated.stockout_probability}
            format={formatShare}
            source={SOURCES.simulation}
            detail={`share of ${runs?.n_runs ?? "the"} runs that ran out of stock`}
          />
        ) : (
          <Missing />
        )}
      </NumberCell>
      <NumberCell>
        <Money value={planned.promo_cost} source={SOURCES.lineEstimate} />
      </NumberCell>
      <NumberCell
        className={cn(
          planned.expected_incremental_profit < 0 && "text-destructive",
        )}
      >
        <Money
          value={planned.expected_incremental_profit}
          source={SOURCES.lineEstimate}
        />
      </NumberCell>
      <td className="px-2 py-2">
        <Notes row={row} />
      </td>
      <td className="px-2 py-2">
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            aria-expanded={expanded}
            aria-label={`Details for ${label}`}
            onClick={onToggle}
          >
            <Chevron aria-hidden />
            Details
          </Button>
          <MechanismDrawer planned={planned} />
        </div>
      </td>
    </tr>
  );
}

function NumberCell({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <td className={cn("px-2 py-2 text-right whitespace-nowrap", className)}>
      {children}
    </td>
  );
}

function Missing() {
  return <span className="text-muted-foreground">—</span>;
}

// A number the optimiser decided, such as the depth or the start week.
function Decision({
  value,
  format,
}: {
  value: number;
  format: (value: number) => string;
}) {
  return (
    <SourcedNumber value={value} format={format} source={SOURCES.decision} />
  );
}

// Money in lakh or crore, with the exact rupees in the tooltip (ADR 0060).
export function Money({ value, source }: { value: number; source: string }) {
  return (
    <SourcedNumber
      value={value}
      format={formatMoney}
      source={source}
      detail={formatRupees(value)}
    />
  );
}

function ProfitRange({
  simulated,
  runs,
}: {
  simulated: LineSimulation;
  runs?: SimulationRuns | null;
}) {
  const { p10, p50, p90 } = simulated.gross_profit;
  const detail = [
    `gross profit over the promo weeks: P10 ${formatMoney(p10)}, P50 ${formatMoney(p50)}, P90 ${formatMoney(p90)}`,
    runs && `${runs.n_runs} runs, seed ${runs.seed}`,
  ]
    .filter(Boolean)
    .join(" · ");
  const bound = (value: number) => (
    <SourcedNumber
      value={value}
      format={formatMoney}
      source={SOURCES.simulation}
      detail={detail}
    />
  );
  return (
    <>
      {bound(p10)} – {bound(p90)}
    </>
  );
}

function Notes({ row }: { row: PlanRow }) {
  const effects = row.planned.cross_effects;
  const notes = [
    effects.some((effect) => effect.units_change_pct <= -MIN_EFFECT_PCT) &&
      "Cannibalisation",
    effects.some((effect) => effect.units_change_pct >= MIN_EFFECT_PCT) &&
      "Halo",
    row.undercut?.undercut && "Undercut",
  ].filter((note): note is string => Boolean(note));
  return (
    <div className="flex flex-wrap gap-1">
      {notes.map((note) => (
        <Badge key={note} variant="outline">
          {note}
        </Badge>
      ))}
    </div>
  );
}

// What sits behind a line's Details toggle: why it was chosen, whom it lifts,
// and the SKUs and competitor prices it touches.
function PlanLineDetails({ row }: { row: PlanRow }) {
  const { planned, rationale, undercut } = row;
  const { line } = planned;
  return (
    <div className="grid gap-3 md:grid-cols-2">
      <div className="flex flex-col gap-3">
        {rationale && (
          <section aria-label="Rationale">
            <h3 className="font-medium">Why this line</h3>
            <p className="text-muted-foreground">{rationale}</p>
          </section>
        )}
        <SegmentUplift planned={planned} />
      </div>
      <div className="flex flex-col gap-2">
        <CannibalisationCallout
          promoted={line.sku_id}
          effects={planned.cross_effects}
        />
        <HaloCallout promoted={line.sku_id} effects={planned.cross_effects} />
        {undercut && <UndercutCallout gaps={[undercut]} />}
      </div>
    </div>
  );
}

function SegmentUplift({ planned }: { planned: PlanRevisionLine }) {
  const { line, segments } = planned;
  if (segments.length === 0) {
    return (
      <p className="text-muted-foreground">
        No segment breakdown was kept for this line.
      </p>
    );
  }
  const units = (value: number) => (
    <SourcedNumber
      value={value}
      format={formatTokens}
      source={SOURCES.segments}
    />
  );
  return (
    <table
      aria-label={`Uplift by segment for ${line.sku_id} in ${line.region}`}
      className="w-full max-w-md"
    >
      <thead>
        <tr className="border-b">
          <th scope="col" className="py-1 text-left font-medium">
            Segment
          </th>
          <th scope="col" className="py-1 text-right font-medium">
            Units
          </th>
          <th scope="col" className="py-1 text-right font-medium">
            Baseline
          </th>
          <th scope="col" className="py-1 text-right font-medium">
            Uplift
          </th>
        </tr>
      </thead>
      <tbody>
        {segments.map((segment) => (
          <tr key={segment.segment}>
            <td className="py-1">{segment.segment}</td>
            <td className="py-1 text-right">{units(segment.units)}</td>
            <td className="py-1 text-right">{units(segment.baseline_units)}</td>
            <td className="py-1 text-right">
              {segment.uplift_pct == null ? (
                <Missing />
              ) : (
                <SourcedNumber
                  value={segment.uplift_pct}
                  format={formatUplift}
                  source={SOURCES.segments}
                />
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
