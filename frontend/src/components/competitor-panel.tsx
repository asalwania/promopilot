import { SourcedNumber } from "@/components/sourced-number";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { CompetitorGap } from "@/lib/api/catalog";
import type { PlanningRequest, PlanRevision } from "@/lib/api/sessions";
import {
  formatMechanism,
  formatPrice,
  formatShare,
  formatWeek,
} from "@/lib/format";
import { SOURCES } from "@/lib/sources";

// The KVI gaps at the request's as-of week, as the page's shared query holds them
// (ADR 0060 D10).
export type CompetitorPrices =
  | { status: "loading" }
  | { status: "error"; reason: string; retry: () => void }
  | { status: "ready"; gaps: CompetitorGap[] };

// Competitor awareness (F-08, SPEC §11): the KVI prices the planner saw, which are
// undercut, the plan line that promotes each, and the planner's response (ADR 0068).
export function CompetitorPanel({
  prices,
  request,
  revision,
}: {
  prices: CompetitorPrices;
  request: PlanningRequest;
  revision: PlanRevision;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Competitor prices</CardTitle>
        <p className="text-muted-foreground text-sm">
          KVI prices before {formatWeek(request.as_of_week)} in the brief&apos;s
          scope, as the planner saw them.
        </p>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {prices.status === "loading" && (
          <p className="text-muted-foreground text-sm">
            Loading competitor prices…
          </p>
        )}
        {prices.status === "error" && (
          <div className="flex items-center justify-between gap-4">
            <p role="alert" className="text-destructive text-sm">
              Couldn&apos;t load competitor prices: {prices.reason}
            </p>
            <Button variant="outline" size="sm" onClick={prices.retry}>
              Retry
            </Button>
          </div>
        )}
        {prices.status === "ready" && (
          <Gaps gaps={inScope(prices.gaps, request)} revision={revision} />
        )}
      </CardContent>
    </Card>
  );
}

// The planner read the gaps of the request's regions, categories and SKUs only
// (ADR 0049 D4). Undercuts first, then as the API ordered them.
function inScope(gaps: CompetitorGap[], request: PlanningRequest) {
  const { regions, categories, sku_ids } = request.scope;
  const kept = gaps.filter(
    (gap) =>
      regions.includes(gap.region) &&
      (categories.length === 0 || categories.includes(gap.category)) &&
      (sku_ids.length === 0 || sku_ids.includes(gap.sku_id)),
  );
  return [
    ...kept.filter((gap) => gap.undercut),
    ...kept.filter((gap) => !gap.undercut),
  ];
}

function Gaps({
  gaps,
  revision,
}: {
  gaps: CompetitorGap[];
  revision: PlanRevision;
}) {
  if (gaps.length === 0) {
    return (
      <p className="text-muted-foreground text-sm">
        No KVI in scope has a competitor price.
      </p>
    );
  }
  const response = revision.explanation?.competitor_response ?? [];
  const undercut = gaps.some((gap) => gap.undercut);
  return (
    <>
      <table aria-label="Competitor gaps" className="w-full text-sm">
        <thead>
          <tr className="border-b">
            {[
              "SKU",
              "Region",
              "Our price",
              "Competitor price",
              "Gap",
              "CPI",
              "Flags",
              "Plan line",
            ].map((column) => (
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
          {gaps.map((gap) => (
            <GapRow
              key={`${gap.region}-${gap.sku_id}`}
              gap={gap}
              revision={revision}
            />
          ))}
        </tbody>
      </table>
      <section
        aria-label="Planner's response"
        className="flex flex-col gap-1 text-sm"
      >
        <h3 className="font-medium">Planner&apos;s response</h3>
        {!undercut ? (
          <p className="text-muted-foreground">
            No KVI in scope is undercut, so the plan answers none.
          </p>
        ) : response.length > 0 ? (
          <ul className="flex list-disc flex-col gap-1 pl-5">
            {response.map((sentence) => (
              <li key={sentence} title={`Source: ${SOURCES.competitorGaps}`}>
                {sentence}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-muted-foreground">
            The plan summary gives the planner&apos;s response.
          </p>
        )}
      </section>
    </>
  );
}

function GapRow({
  gap,
  revision,
}: {
  gap: CompetitorGap;
  revision: PlanRevision;
}) {
  const detail = `competitor price in ${formatWeek(gap.price_week)}`;
  const sourced = (value: number, format: (n: number) => string) => (
    <SourcedNumber
      value={value}
      format={format}
      source={SOURCES.competitorGaps}
      detail={detail}
    />
  );
  return (
    <tr className="border-b align-top">
      <td className="px-2 py-2">
        <div className="font-mono">{gap.sku_id}</div>
        <div className="text-muted-foreground">{gap.name}</div>
      </td>
      <td className="px-2 py-2">{gap.region}</td>
      <td className="px-2 py-2 whitespace-nowrap">
        {sourced(gap.base_price, formatPrice)}
      </td>
      <td className="px-2 py-2 whitespace-nowrap">
        {sourced(gap.competitor_price, formatPrice)}
      </td>
      <td className="px-2 py-2">{sourced(gap.gap, formatShare)}</td>
      <td className="px-2 py-2">{sourced(gap.cpi, (n) => n.toFixed(2))}</td>
      <td className="px-2 py-2">
        <div className="flex flex-wrap gap-1">
          {gap.undercut && <Badge variant="destructive">Undercut</Badge>}
          {gap.competitor_on_promo && <Badge variant="outline">On promo</Badge>}
        </div>
      </td>
      <td className="px-2 py-2">
        <PlanLine gap={gap} revision={revision} />
      </td>
    </tr>
  );
}

// The plan line that promotes this SKU in this region, as its anchor or as a
// BUNDLE's partner: a lookup, never a price comparison (ADR 0068 D6).
function PlanLine({
  gap,
  revision,
}: {
  gap: CompetitorGap;
  revision: PlanRevision;
}) {
  const planned = revision.lines.find(
    ({ line }) =>
      line.region === gap.region &&
      (line.sku_id === gap.sku_id || line.bundle_partner_sku_id === gap.sku_id),
  );
  if (!planned) {
    return <span className="text-muted-foreground">Not promoted</span>;
  }
  const { line } = planned;
  return (
    <span>
      {formatMechanism(line.mechanism)}{" "}
      <SourcedNumber
        value={line.depth_pct}
        format={(n) => `${n}%`}
        source={SOURCES.decision}
      />
      {line.sku_id !== gap.sku_id && (
        <span className="text-muted-foreground">
          {" "}
          with <span className="font-mono">{line.sku_id}</span>
        </span>
      )}
    </span>
  );
}
