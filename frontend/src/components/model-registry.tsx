import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { ModelEntry } from "@/lib/api/models";
import { formatDateTime, formatWeek } from "@/lib/format";
import { formatMetric, metricLabel } from "@/lib/model-metrics";

const FIXED_COLUMNS = ["Version", "Status", "Trained", "As-of week"];

// Renders the registry newest first as the API lists it: one card per kind,
// one row per version (ADR 0030).
export function ModelRegistry({ models }: { models: ModelEntry[] }) {
  if (models.length === 0) {
    return (
      <Card className="w-full">
        <CardContent>
          <p className="text-muted-foreground text-sm">
            No model is registered yet. Run <code>make train</code> or click
            Retrain.
          </p>
        </CardContent>
      </Card>
    );
  }
  return (
    <div className="flex w-full flex-col gap-4">
      {groupByKind(models).map(([kind, versions]) => (
        <KindCard key={kind} kind={kind} versions={versions} />
      ))}
    </div>
  );
}

function KindCard({
  kind,
  versions,
}: {
  kind: string;
  versions: ModelEntry[];
}) {
  const title = `${kind.charAt(0).toUpperCase()}${kind.slice(1)} model`;
  const metricKeys = [
    ...new Set(versions.flatMap((entry) => Object.keys(entry.metrics))),
  ];
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>{title}</h2>
        </CardTitle>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        <table aria-label={`${title} versions`} className="w-full text-sm">
          <thead>
            <tr className="border-b">
              {FIXED_COLUMNS.map((column) => (
                <th
                  key={column}
                  scope="col"
                  className="text-muted-foreground px-2 py-2 text-left font-medium"
                >
                  {column}
                </th>
              ))}
              {metricKeys.map((key) => (
                <th
                  key={key}
                  scope="col"
                  className="text-muted-foreground px-2 py-2 text-right font-medium"
                >
                  {metricLabel(key)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {versions.map((entry) => (
              <tr key={entry.model_id} className="border-b">
                <td className="px-2 py-2 tabular-nums">v{entry.version}</td>
                <td className="px-2 py-2">
                  {entry.live && <Badge>Live</Badge>}
                </td>
                <td className="px-2 py-2">
                  {formatDateTime(entry.trained_at)}
                </td>
                <td className="px-2 py-2">{formatWeek(entry.as_of_week)}</td>
                {metricKeys.map((key) => (
                  <td key={key} className="px-2 py-2 text-right tabular-nums">
                    {key in entry.metrics
                      ? formatMetric(key, entry.metrics[key])
                      : "—"}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

function groupByKind(models: ModelEntry[]): [string, ModelEntry[]][] {
  const groups = new Map<string, ModelEntry[]>();
  for (const entry of models) {
    groups.set(entry.kind, [...(groups.get(entry.kind) ?? []), entry]);
  }
  return [...groups];
}
