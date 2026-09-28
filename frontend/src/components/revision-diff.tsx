import { useId } from "react";

import { SourcedNumber } from "@/components/sourced-number";
import { Badge } from "@/components/ui/badge";
import type {
  Amendment,
  LineChange,
  PlanExplanation,
  PlanRevisionLine,
  RevisionDiff,
} from "@/lib/api/sessions";
import { fieldLabel } from "@/lib/assumptions";
import { formatMechanism, formatMoney, formatWeek } from "@/lib/format";
import { SOURCES } from "@/lib/sources";
import { cn } from "@/lib/utils";

type Line = PlanRevisionLine["line"];

// The plan-line fields that make a line's decision (ADR 0052 D8), as a manager reads them.
const DECISION_FIELDS: Record<string, string> = {
  mechanism: "Mechanism",
  depth_pct: "Depth",
  start_week: "Start",
  duration_weeks: "Duration",
  target_segment: "Target segment",
  bundle_partner_sku_id: "Bundle partner",
};

const LINE_COLUMNS = [
  "SKU",
  "Region",
  "Mechanism",
  "Depth",
  "Start",
  "Duration",
  "Target segment",
  "Promo cost",
  "Expected incremental profit",
];
const NUMERIC = new Set(["Promo cost", "Expected incremental profit"]);

// What an amendment changed (AG-05, ADR 0052): the stored diff of the latest plan
// revision against the one before it, and the Explainer's words for it (ADR 0066).
export function RevisionDiffView({
  diff,
  explanation,
  amendment,
}: {
  diff: RevisionDiff;
  explanation?: PlanExplanation | null;
  // The amendment that led from the previous revision to this one, if known.
  amendment?: Amendment;
}) {
  const headingId = useId();
  const from = diff.from_revision;
  const lineChanges =
    diff.added.length + diff.removed.length + diff.changed.length;
  return (
    <section
      aria-labelledby={headingId}
      className="bg-muted/30 flex flex-col gap-3 rounded-lg border p-3 text-sm"
    >
      <div className="flex flex-col gap-1">
        <h3 id={headingId} className="font-medium">
          What changed from plan revision {from}
        </h3>
        {amendment && (
          <p className="text-muted-foreground">
            After your amendment “{amendment.text}”
            {amendment.relaxation && " (the accepted relaxation)"}.
          </p>
        )}
      </div>
      {explanation?.changes && (
        <p className="flex flex-col gap-1">
          <span>{explanation.changes}</span>
          {explanation.source === "template" && (
            <Badge variant="outline">Template explanation</Badge>
          )}
        </p>
      )}
      {diff.request_changes.length > 0 && (
        <ul aria-label="Request changes" className="flex flex-col gap-0.5">
          {diff.request_changes.map((change) => (
            <li key={change.field}>
              <span className="font-medium">{fieldLabel(change.field)}:</span>{" "}
              {change.before} → {change.after}
            </li>
          ))}
        </ul>
      )}
      <Totals diff={diff} />
      {lineChanges === 0 ? (
        <p>No plan line changed.</p>
      ) : (
        <>
          {diff.added.length > 0 && (
            <LineTable label="Added plan lines" lines={diff.added} />
          )}
          {diff.removed.length > 0 && (
            <LineTable label="Removed plan lines" lines={diff.removed} />
          )}
          {diff.changed.length > 0 && <ChangedTable changes={diff.changed} />}
        </>
      )}
      {diff.unchanged > 0 && (
        <p className="text-muted-foreground">
          {diff.unchanged} plan {diff.unchanged === 1 ? "line" : "lines"}{" "}
          unchanged.
        </p>
      )}
    </section>
  );
}

function Totals({ diff }: { diff: RevisionDiff }) {
  const from = `plan revision ${diff.from_revision}`;
  const objective = (detail: string, value?: number | null) =>
    value == null ? (
      <Missing />
    ) : (
      <SourcedNumber
        value={value}
        format={formatMoney}
        source={SOURCES.decision}
        detail={detail}
      />
    );
  const cost = (detail: string, value: number, signed = false) => (
    <SourcedNumber
      value={value}
      format={signed ? signedMoney : formatMoney}
      source={SOURCES.lineEstimate}
      detail={detail}
    />
  );
  return (
    <table aria-label="Plan totals" className="w-fit text-sm">
      <thead>
        <tr className="border-b">
          <th scope="col" className="sr-only">
            Total
          </th>
          {["Before", "After", "Change"].map((column) => (
            <th
              key={column}
              scope="col"
              className="text-muted-foreground px-2 py-1 text-right font-medium"
            >
              {column}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        <tr>
          <th scope="row" className="pr-4 text-left font-medium">
            Objective
          </th>
          <NumberCell>
            {objective(
              `the optimiser's objective for ${from}`,
              diff.objective_before,
            )}
          </NumberCell>
          <NumberCell>
            {objective(
              "the optimiser's objective for this revision",
              diff.objective_after,
            )}
          </NumberCell>
          <NumberCell>
            {diff.objective_delta == null ? (
              <Missing />
            ) : (
              <SourcedNumber
                value={diff.objective_delta}
                format={signedMoney}
                source={SOURCES.decision}
                detail={`this revision's objective less ${from}'s`}
              />
            )}
          </NumberCell>
        </tr>
        <tr>
          <th scope="row" className="pr-4 text-left font-medium">
            Promo cost
          </th>
          <NumberCell>
            {cost(
              `the sum of ${from}'s plan lines' promo cost`,
              diff.promo_cost_before,
            )}
          </NumberCell>
          <NumberCell>
            {cost(
              "the sum of this revision's plan lines' promo cost",
              diff.promo_cost_after,
            )}
          </NumberCell>
          <NumberCell>
            {cost(
              `this revision's promo cost less ${from}'s`,
              diff.promo_cost_delta,
              true,
            )}
          </NumberCell>
        </tr>
      </tbody>
    </table>
  );
}

function LineTable({
  label,
  lines,
}: {
  label: string;
  lines: PlanRevisionLine[];
}) {
  return (
    <table aria-label={label} className="w-full text-sm">
      <caption className="text-left font-medium">
        {label.replace(" plan lines", "")} ({lines.length})
      </caption>
      <thead>
        <tr className="border-b">
          {LINE_COLUMNS.map((column) => (
            <th
              key={column}
              scope="col"
              className={cn(
                "text-muted-foreground px-2 py-1 font-medium",
                NUMERIC.has(column) ? "text-right" : "text-left",
              )}
            >
              {column}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {lines.map((planned) => {
          const { line } = planned;
          return (
            <tr key={`${line.sku_id}-${line.region}`} className="border-b">
              <td className="px-2 py-1 font-mono">{line.sku_id}</td>
              <td className="px-2 py-1">{line.region}</td>
              <td className="px-2 py-1">
                {formatMechanism(line.mechanism)}
                {line.bundle_partner_sku_id && (
                  <span className="text-muted-foreground font-mono">
                    {" "}
                    + {line.bundle_partner_sku_id}
                  </span>
                )}
              </td>
              <td className="px-2 py-1">{decisionValue(line, "depth_pct")}</td>
              <td className="px-2 py-1">{decisionValue(line, "start_week")}</td>
              <td className="px-2 py-1">
                {decisionValue(line, "duration_weeks")}
              </td>
              <td className="px-2 py-1">{line.target_segment}</td>
              <NumberCell>
                <SourcedNumber
                  value={planned.promo_cost}
                  format={formatMoney}
                  source={SOURCES.lineEstimate}
                  detail={`exactly ${formatMoney(planned.promo_cost)}`}
                />
              </NumberCell>
              <NumberCell>
                <SourcedNumber
                  value={planned.expected_incremental_profit}
                  format={formatMoney}
                  source={SOURCES.lineEstimate}
                  detail="expected incremental profit of the line"
                />
              </NumberCell>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function ChangedTable({ changes }: { changes: LineChange[] }) {
  return (
    <table aria-label="Changed plan lines" className="w-full text-sm">
      <caption className="text-left font-medium">
        Changed ({changes.length})
      </caption>
      <thead>
        <tr className="border-b">
          {["SKU", "Region", "What changed"].map((column) => (
            <th
              key={column}
              scope="col"
              className="text-muted-foreground px-2 py-1 text-left font-medium"
            >
              {column}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {changes.map((change) => (
          <tr key={`${change.sku_id}-${change.region}`} className="border-b">
            <td className="px-2 py-1 font-mono">{change.sku_id}</td>
            <td className="px-2 py-1">{change.region}</td>
            <td className="px-2 py-1">
              <ul className="flex flex-col gap-0.5">
                {change.fields.map((field) => (
                  <li key={field}>
                    <span className="font-medium">
                      {DECISION_FIELDS[field] ?? field}
                    </span>{" "}
                    {decisionValue(change.before.line, field)} →{" "}
                    {decisionValue(change.after.line, field)}
                  </li>
                ))}
              </ul>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// One decision field of a line as the plan table shows it; its numbers name the
// optimiser (ADR 0060).
function decisionValue(line: Line, field: string): React.ReactNode {
  const decision = (value: number, format: (n: number) => string) => (
    <SourcedNumber value={value} format={format} source={SOURCES.decision} />
  );
  switch (field) {
    case "mechanism":
      return formatMechanism(line.mechanism);
    case "depth_pct":
      return decision(line.depth_pct, (n) => `${n}%`);
    case "start_week":
      return decision(line.start_week, formatWeek);
    case "duration_weeks":
      return decision(line.duration_weeks, (n) => `${n} wk`);
    case "target_segment":
      return line.target_segment;
    case "bundle_partner_sku_id":
      return line.bundle_partner_sku_id ?? "none";
    default:
      return String((line as Record<string, unknown>)[field] ?? "—");
  }
}

// A change of money, signed both ways, e.g. +₹5,000 or -₹1.24 lakh.
function signedMoney(amount: number): string {
  const shown = formatMoney(amount);
  return amount > 0 && /[1-9]/.test(shown) ? `+${shown}` : shown;
}

function NumberCell({ children }: { children: React.ReactNode }) {
  return <td className="px-2 py-1 text-right tabular-nums">{children}</td>;
}

function Missing() {
  return <span className="text-muted-foreground">—</span>;
}
