import type { PlanRevisionLine } from "@/lib/api/sessions";
import { formatMechanism, formatRupees, formatWeek } from "@/lib/format";
import { cn } from "@/lib/utils";

const COLUMNS = [
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
const NUMERIC_FROM = COLUMNS.indexOf("Promo cost");

export function PlanTable({ lines }: { lines: PlanRevisionLine[] }) {
  return (
    <table aria-label="Plan lines" className="w-full text-sm">
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
        {lines.map(({ line, promo_cost, expected_incremental_profit }) => (
          <tr key={`${line.sku_id}-${line.region}`} className="border-b">
            <td className="px-2 py-2 font-mono">{line.sku_id}</td>
            <td className="px-2 py-2">{line.region}</td>
            <td className="px-2 py-2">{formatMechanism(line.mechanism)}</td>
            <td className="px-2 py-2">{line.depth_pct}%</td>
            <td className="px-2 py-2">{formatWeek(line.start_week)}</td>
            <td className="px-2 py-2">{line.duration_weeks} wk</td>
            <td className="px-2 py-2">{line.target_segment}</td>
            <td className="px-2 py-2 text-right tabular-nums">
              {formatRupees(promo_cost)}
            </td>
            <td
              className={cn(
                "px-2 py-2 text-right tabular-nums",
                expected_incremental_profit < 0 && "text-destructive",
              )}
            >
              {formatRupees(expected_incremental_profit)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
