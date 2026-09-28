import { cn } from "cn";

import { SourcedNumber } from "@/components/sourced-number";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { Assumption, SessionStatus } from "@/lib/api/sessions";
import { fieldLabel, isLowConfidence, needsAttention } from "@/lib/assumptions";

const SOURCE_LABELS: Record<Assumption["source"], string> = {
  brief: "From brief",
  data: "From data",
  default: "Default",
};

// Where each confidence comes from (ADR 0048 D1, D2, D9; ADR 0053 D6).
const CONFIDENCE_DETAIL: Record<Assumption["source"], string> = {
  brief: "how closely the brief's words match the catalogue",
  data: "how closely the brief's holiday matches the calendar, or 1 for a fact from data",
  default: "1 for a company-policy default",
};

const percentFormat = new Intl.NumberFormat("en-IN", {
  style: "percent",
  maximumFractionDigits: 0,
});

// What the agent assumed, with source and confidence (AG-01, SPEC §11). Low-confidence
// and flagged readings, such as a brief value company policy overrode, stand out so the
// manager can spot a wrong guess (ADR 0061).
export function AssumptionsPanel({
  assumptions,
  status,
}: {
  assumptions: Assumption[];
  status: SessionStatus;
}) {
  const attention = assumptions.filter(needsAttention).length;
  const fallback = assumptions.some((assumption) => assumption.fallback);
  return (
    <Card role="region" aria-labelledby="assumptions-title">
      <CardHeader>
        <CardTitle id="assumptions-title">Assumptions</CardTitle>
        {assumptions.length > 0 && (
          <CardDescription>
            {attention === 0
              ? "None need a look"
              : `${attention} ${attention === 1 ? "needs" : "need"} a look`}
          </CardDescription>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {fallback && (
          <p
            role="note"
            className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-100"
          >
            The language model was unavailable: these were read by rules.
          </p>
        )}
        {assumptions.length > 0 ? (
          <AssumptionTable assumptions={assumptions} />
        ) : (
          <p className="text-muted-foreground text-sm">
            {status === "planning"
              ? "The Context agent is reading the brief…"
              : "No assumptions were recorded."}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function AssumptionTable({ assumptions }: { assumptions: Assumption[] }) {
  return (
    <table aria-label="Assumptions" className="w-full text-sm">
      <thead>
        <tr className="border-b">
          {["Field", "Value", "Source", "Confidence"].map((heading) => (
            <th
              key={heading}
              scope="col"
              className={cn(
                "text-muted-foreground px-2 py-2 text-left font-medium",
                heading === "Confidence" && "text-right",
              )}
            >
              {heading}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {/* A field can repeat: each clearance ask is its own assumption. */}
        {assumptions.map((assumption, index) => (
          <AssumptionRow
            key={`${assumption.field}-${index}`}
            assumption={assumption}
          />
        ))}
      </tbody>
    </table>
  );
}

function AssumptionRow({ assumption }: { assumption: Assumption }) {
  const low = isLowConfidence(assumption);
  return (
    <tr
      className={cn(
        "border-b align-top",
        needsAttention(assumption) && "bg-amber-50 dark:bg-amber-950/40",
      )}
    >
      <th scope="row" className="px-2 py-2 text-left font-medium">
        {fieldLabel(assumption.field)}
      </th>
      <td className="px-2 py-2">
        {assumption.value}
        {assumption.flagged && (
          <span className="mt-1 flex items-start gap-2">
            <Badge variant="destructive">Flagged</Badge>
            {assumption.note && (
              <span className="text-muted-foreground text-xs">
                {assumption.note}
              </span>
            )}
          </span>
        )}
        {!assumption.flagged && assumption.note && (
          <span className="text-muted-foreground mt-1 block text-xs">
            {assumption.note}
          </span>
        )}
      </td>
      <td className="px-2 py-2">
        <span className="flex flex-wrap gap-1">
          <Badge variant="outline">{SOURCE_LABELS[assumption.source]}</Badge>
          {assumption.fallback && (
            <Badge variant="secondary">Read by rules</Badge>
          )}
        </span>
      </td>
      <td className="px-2 py-2 text-right">
        <span className="flex flex-wrap items-center justify-end gap-1">
          <SourcedNumber
            value={assumption.confidence}
            format={(value) => percentFormat.format(value)}
            source="Context agent"
            detail={CONFIDENCE_DETAIL[assumption.source]}
          />
          {low && <Badge variant="destructive">Low confidence</Badge>}
        </span>
      </td>
    </tr>
  );
}
