import { SourcedNumber } from "@/components/sourced-number";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { PlanRevision } from "@/lib/api/sessions";
import { formatMechanism, formatMoney, formatWeek } from "@/lib/format";
import { SOURCES } from "@/lib/sources";

type NotSelectedOption = PlanRevision["not_selected"][number];
type NotSelectedReason = NotSelectedOption["reasons"][number];

// Why the optimiser left an option out (F-01 AC3, ADR 0038, ADR 0040, ADR 0075).
const REASON_LABELS: Record<
  Exclude<NotSelectedReason, "cannibalises" | "strong_substitute">,
  string
> = {
  low_uplift: "Low uplift: not worth it on its own",
  out_of_stock: "Not enough stock for its P90 units",
  breaks_policy:
    "Breaks company policy: promo window, maximum discount or unit cost",
  over_budget: "Over the marketing budget",
  over_regional_budget: "Over the regional budget cap",
  breaks_margin: "Breaks the minimum margin",
  max_promoted_skus: "Too many promoted SKUs in its category and region",
  misses_clearance_target: "Would leave a clearance target unmet",
  breaks_kvi_tolerance: "Breaks the KVI price tolerance",
  time_limit: "Not settled before the solver's time limit",
};

function reasonLabel(
  reason: NotSelectedReason,
  option: NotSelectedOption,
): string {
  if (reason === "strong_substitute") {
    return option.cannibalises.length > 0
      ? `Strong substitute of ${option.cannibalises.join(", ")}, which the plan promotes at the same time`
      : "Strong substitute of a SKU the plan promotes at the same time";
  }
  if (reason !== "cannibalises") return REASON_LABELS[reason];
  return option.cannibalises.length > 0
    ? `Cannibalises ${option.cannibalises.join(", ")}`
    : "Cannibalises the plan's lines";
}

const COLUMNS = [
  "SKU",
  "Region",
  "Mechanism",
  "Depth",
  "Start",
  "Duration",
  "Target segment",
  "Value alone",
  "Why not selected",
];

// The best options left out, best first, one per SKU and region (F-01 AC3, ADR 0067).
export function NotSelectedList({ options }: { options: NotSelectedOption[] }) {
  return (
    <Card role="region" aria-labelledby="not-selected-title">
      <CardHeader>
        <CardTitle id="not-selected-title">Not selected</CardTitle>
        {options.length > 0 && (
          <CardDescription>
            The best options the optimiser left out, best first
          </CardDescription>
        )}
      </CardHeader>
      <CardContent>
        {options.length > 0 ? (
          <table aria-label="Not selected options" className="w-full text-sm">
            <thead>
              <tr className="border-b">
                {COLUMNS.map((heading) => (
                  <th
                    key={heading}
                    scope="col"
                    className="text-muted-foreground px-2 py-2 text-left font-medium"
                  >
                    {heading}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {options.map((entry) => (
                <OptionRow
                  key={`${entry.option.sku_id}-${entry.option.region}`}
                  entry={entry}
                />
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-muted-foreground text-sm">
            No worthwhile option was left out.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function OptionRow({ entry }: { entry: NotSelectedOption }) {
  const { option } = entry;
  const decided = (value: number, format: (n: number) => string) => (
    <SourcedNumber value={value} format={format} source={SOURCES.notSelected} />
  );
  return (
    <tr className="border-b align-top">
      <th scope="row" className="px-2 py-2 text-left font-medium">
        {option.sku_id}
      </th>
      <td className="px-2 py-2">{option.region}</td>
      <td className="px-2 py-2">
        {formatMechanism(option.mechanism)}
        {option.bundle_partner_sku_id && ` + ${option.bundle_partner_sku_id}`}
      </td>
      <td className="px-2 py-2">{decided(option.depth_pct, (n) => `${n}%`)}</td>
      <td className="px-2 py-2">{decided(option.start_week, formatWeek)}</td>
      <td className="px-2 py-2">
        {decided(option.duration_weeks, (n) => `${n} wk`)}
      </td>
      <td className="px-2 py-2">{option.target_segment}</td>
      <td className="px-2 py-2 text-right">
        <SourcedNumber
          value={entry.value}
          format={formatMoney}
          source={SOURCES.notSelected}
          detail="what it is worth alone: incremental profit − cannibalisation + halo + clearance value"
        />
      </td>
      <td className="px-2 py-2">
        <ul aria-label="Reasons" className="flex flex-col gap-1">
          {entry.reasons.map((reason) => (
            <li key={reason}>{reasonLabel(reason, entry)}</li>
          ))}
        </ul>
      </td>
    </tr>
  );
}
