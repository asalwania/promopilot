import { TriangleAlert } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { components } from "@/lib/api/schema";
import { formatPrice } from "@/lib/format";
import { SOURCES } from "@/lib/sources";

type CompetitorGap = components["schemas"]["CompetitorGap"];

// Presentational: E10 places it on the session page's competitor panel (ADR 0031).
export function UndercutCallout({ gaps }: { gaps: CompetitorGap[] }) {
  const undercuts = gaps.filter((gap) => gap.undercut);
  if (undercuts.length === 0) {
    return null;
  }
  return (
    <aside
      role="note"
      aria-labelledby="undercut-callout-title"
      className="flex flex-col gap-2 rounded-lg border border-amber-500/50 bg-amber-500/10 p-3 text-sm"
    >
      <p
        id="undercut-callout-title"
        className="flex items-center gap-2 font-medium"
      >
        <TriangleAlert aria-hidden className="size-4 text-amber-600" />
        Competitor undercuts
      </p>
      <ul className="flex flex-col gap-1">
        {undercuts.map((gap) => (
          <li
            key={`${gap.region}-${gap.sku_id}`}
            title={`Source: ${SOURCES.competitorGaps}`}
            className="flex flex-wrap items-center gap-2"
          >
            <span>
              Competitor is {(gap.gap * 100).toFixed(1)}% cheaper on {gap.name}{" "}
              in {gap.region} ({formatPrice(gap.competitor_price)} vs{" "}
              {formatPrice(gap.base_price)})
            </span>
            {gap.competitor_on_promo && (
              <Badge variant="outline">On promo</Badge>
            )}
          </li>
        ))}
      </ul>
    </aside>
  );
}
