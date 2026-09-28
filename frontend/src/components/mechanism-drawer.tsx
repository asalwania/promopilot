"use client";

import { Scale } from "lucide-react";

import { SourcedNumber } from "@/components/sourced-number";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import type { MechanismOutcome, PlanRevisionLine } from "@/lib/api/sessions";
import {
  formatMechanism,
  formatMoney,
  formatRupees,
  formatShare,
  formatTokens,
  formatWeek,
} from "@/lib/format";
import { SOURCES } from "@/lib/sources";
import { cn } from "@/lib/utils";

type Unavailable = MechanismOutcome["unavailable"][number];

const UNAVAILABLE: Record<Unavailable, string> = {
  no_charm_price: "no charm price",
  max_discount: "deeper than the maximum discount",
  below_cost: "below cost",
  duplicate_price: "the same price as another option",
  stock: "not enough stock",
  partner_stock: "not enough of the bundle partner",
};

const COLUMNS = [
  "Mechanism",
  "Best option",
  "Units",
  "Margin",
  "Promo cost",
  "Incremental profit",
  "Value",
];
const NUMERIC_FROM = COLUMNS.indexOf("Units");

// Why the line's mechanism was chosen: each mechanism's best option for the
// line's SKU and region, next to the chosen one (F-02, ADR 0041, ADR 0060).
export function MechanismDrawer({ planned }: { planned: PlanRevisionLine }) {
  const { line, mechanism_comparison: comparison } = planned;
  if (comparison.length === 0) return null;
  const label = `${line.sku_id} in ${line.region}`;
  const bundle = comparison.find(
    (outcome) => outcome.mechanism === "BUNDLE" && outcome.best,
  )?.best;
  return (
    <Sheet>
      <SheetTrigger
        render={
          <Button
            variant="ghost"
            size="sm"
            aria-label={`Compare mechanisms for ${label}`}
          />
        }
      >
        <Scale aria-hidden />
        Mechanisms
      </SheetTrigger>
      <SheetContent
        side="right"
        className="w-full overflow-y-auto data-[side=right]:sm:max-w-3xl"
      >
        <SheetHeader>
          <SheetTitle>Mechanisms for {label}</SheetTitle>
          <SheetDescription>
            Each mechanism&apos;s best option for this SKU and region, from{" "}
            <code>{SOURCES.mechanisms}</code>.
          </SheetDescription>
        </SheetHeader>
        <div className="flex flex-col gap-4 px-4 pb-4">
          {bundle && bundle.partner_sku_id && (
            <section
              aria-label="Bundle suggestion"
              className="rounded-lg border border-sky-500/40 bg-sky-500/5 px-3 py-2"
            >
              Bundle <span className="font-mono">{bundle.anchor_sku_id}</span>{" "}
              with <span className="font-mono">{bundle.partner_sku_id}</span>
              {bundle.basket_lift != null && (
                <>
                  : basket lift{" "}
                  <SourcedNumber
                    value={bundle.basket_lift}
                    format={(lift) => `${lift}×`}
                    source={SOURCES.mechanisms}
                    detail="how much more often the pair is bought together than by chance"
                  />
                </>
              )}
              , expected incremental profit{" "}
              <Figure value={bundle.incremental_profit} />
            </section>
          )}
          <table aria-label="Mechanism comparison" className="w-full text-sm">
            <thead>
              <tr className="border-b">
                {COLUMNS.map((column, index) => (
                  <th
                    key={column}
                    scope="col"
                    className={cn(
                      "text-muted-foreground px-2 py-2 font-medium",
                      index >= NUMERIC_FROM ? "text-right" : "text-left",
                    )}
                  >
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {comparison.map((outcome) => (
                <OutcomeRow key={outcome.mechanism} outcome={outcome} />
              ))}
            </tbody>
          </table>
        </div>
      </SheetContent>
    </Sheet>
  );
}

function OutcomeRow({ outcome }: { outcome: MechanismOutcome }) {
  const { best } = outcome;
  const name = (
    <td className="px-2 py-2">
      <span className="flex items-center gap-2">
        {formatMechanism(outcome.mechanism)}
        {outcome.chosen && <Badge>Chosen</Badge>}
      </span>
    </td>
  );
  if (!best) {
    return (
      <tr className="border-b">
        {name}
        <td className="text-muted-foreground px-2 py-2">
          No option: {outcome.unavailable.map((u) => UNAVAILABLE[u]).join(", ")}
        </td>
        {COLUMNS.slice(NUMERIC_FROM).map((column) => (
          <td key={column} />
        ))}
      </tr>
    );
  }
  const { option } = best;
  return (
    <tr className={cn("border-b", outcome.chosen && "bg-muted/40")}>
      {name}
      <td className="px-2 py-2">
        {option.depth_pct}% · {option.duration_weeks} wk from{" "}
        {formatWeek(option.start_week)} · {option.target_segment}
      </td>
      <Cell>
        <SourcedNumber
          value={best.units}
          format={formatTokens}
          source={SOURCES.mechanisms}
        />
      </Cell>
      <Cell>
        <SourcedNumber
          value={best.margin}
          format={formatShare}
          source={SOURCES.mechanisms}
        />
      </Cell>
      <Cell>
        <Figure value={best.promo_cost} />
      </Cell>
      <Cell>
        <Figure value={best.incremental_profit} />
      </Cell>
      <Cell>
        <Figure value={best.value} />
      </Cell>
    </tr>
  );
}

function Cell({ children }: { children: React.ReactNode }) {
  return <td className="px-2 py-2 text-right whitespace-nowrap">{children}</td>;
}

function Figure({ value }: { value: number }) {
  return (
    <SourcedNumber
      value={value}
      format={formatMoney}
      source={SOURCES.mechanisms}
      detail={formatRupees(value)}
    />
  );
}
