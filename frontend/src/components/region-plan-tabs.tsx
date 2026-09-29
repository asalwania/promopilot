"use client";

import { Money, PlanTable, type PlanRow } from "@/components/plan-table";
import { SourcedNumber } from "@/components/sourced-number";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { CompetitorGap } from "@/lib/api/catalog";
import type { PlanRevision, Region } from "@/lib/api/sessions";
import { formatMechanism, formatShare } from "@/lib/format";
import { SOURCES } from "@/lib/sources";

const REGION_ORDER: Region[] = ["North", "South", "East", "West"];
const COMPARE = "compare";

// The plan reviewed region by region (F-07): a tab per region of the request,
// then one that puts each SKU's regional lines side by side (ADR 0060).
export function RegionPlanTabs({
  revision,
  regions,
  competitorGaps = [],
}: {
  revision: PlanRevision;
  regions: Region[];
  competitorGaps?: CompetitorGap[];
}) {
  const rows = planRows(revision, competitorGaps);
  const shown = REGION_ORDER.filter(
    (region) =>
      regions.includes(region) ||
      rows.some((row) => row.planned.line.region === region),
  );
  const rowsIn = (region: Region) =>
    rows.filter((row) => row.planned.line.region === region);
  const first =
    shown.find((region) => rowsIn(region).length > 0) ?? shown[0] ?? COMPARE;
  const simulation = revision.simulation;
  const runs = simulation
    ? { n_runs: simulation.n_runs, seed: simulation.seed }
    : null;

  const reaction = simulation?.competitor_reaction;

  return (
    <Tabs defaultValue={first}>
      {reaction && (
        // The stored simulation is a stress test until the next plain one (ADR 0045).
        <p className="text-muted-foreground text-sm">
          Profit ranges and stock-out risks below are from the stress test: the
          competitor matches each plan line&apos;s discount with probability{" "}
          {formatShare(reaction.match_probability)}.
        </p>
      )}
      <TabsList aria-label="Plan regions">
        {shown.map((region) => (
          <TabsTrigger key={region} value={region}>
            {region} ({rowsIn(region).length})
          </TabsTrigger>
        ))}
        <TabsTrigger value={COMPARE}>Compare regions</TabsTrigger>
      </TabsList>
      {shown.map((region) => {
        const regional = rowsIn(region);
        const risk = simulation?.regions.find((r) => r.region === region);
        return (
          <TabsContent
            key={region}
            value={region}
            className="flex flex-col gap-2"
          >
            {risk && (
              <p className="text-muted-foreground">
                Stock-out risk in {region}:{" "}
                <SourcedNumber
                  value={risk.stockout_probability}
                  format={formatShare}
                  source={SOURCES.simulation}
                  detail={`share of ${simulation!.n_runs} runs in which a ${region} plan line ran out`}
                />
              </p>
            )}
            {regional.length > 0 ? (
              <PlanTable region={region} rows={regional} runs={runs} />
            ) : (
              <p className="text-muted-foreground">No plan line in {region}.</p>
            )}
          </TabsContent>
        );
      })}
      <TabsContent value={COMPARE}>
        <RegionComparison
          rows={rows}
          regions={shown.filter((region) => rowsIn(region).length > 0)}
        />
      </TabsContent>
    </Tabs>
  );
}

// Each plan line with its simulated ranges, its rationale (the Explainer keeps
// them in plan-line order, ADR 0050) and any competitor gap on its SKU and region.
function planRows(
  revision: PlanRevision,
  competitorGaps: CompetitorGap[],
): PlanRow[] {
  const key = (sku: string, region: string) => `${sku}|${region}`;
  const simulated = new Map(
    (revision.simulation?.lines ?? []).map((line) => [
      key(line.sku_id, line.region),
      line,
    ]),
  );
  const gaps = new Map(
    competitorGaps.map((gap) => [key(gap.sku_id, gap.region), gap]),
  );
  return revision.lines.map((planned, index) => {
    const at = key(planned.line.sku_id, planned.line.region);
    return {
      planned,
      simulated: simulated.get(at),
      rationale: revision.explanation?.rationales[index],
      undercut: gaps.get(at),
    };
  });
}

// The same SKU in each region, in plan order of its first line (F-07 AC2).
function RegionComparison({
  rows,
  regions,
}: {
  rows: PlanRow[];
  regions: Region[];
}) {
  const skus = [...new Set(rows.map((row) => row.planned.line.sku_id))];
  const lineOf = (sku: string, region: Region) =>
    rows.find(
      (row) =>
        row.planned.line.sku_id === sku && row.planned.line.region === region,
    )?.planned;
  return (
    <table aria-label="Regions side by side" className="w-full text-sm">
      <thead>
        <tr className="border-b">
          {["SKU", ...regions].map((column) => (
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
        {skus.map((sku) => (
          <tr key={sku} className="border-b align-top">
            <td className="px-2 py-2 font-mono">{sku}</td>
            {regions.map((region) => {
              const planned = lineOf(sku, region);
              if (!planned) {
                return (
                  <td key={region} className="text-muted-foreground px-2 py-2">
                    —
                  </td>
                );
              }
              const { line } = planned;
              return (
                <td key={region} className="px-2 py-2">
                  <div>
                    {formatMechanism(line.mechanism)} {line.depth_pct}% ·{" "}
                    {line.duration_weeks} wk · {line.target_segment}
                  </div>
                  <div className="text-muted-foreground">
                    <Money
                      value={planned.expected_incremental_profit}
                      source={SOURCES.lineEstimate}
                    />
                  </div>
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
