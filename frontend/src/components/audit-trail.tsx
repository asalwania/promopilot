import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { Amendment, PlanDecision } from "@/lib/api/sessions";
import { formatDateTime } from "@/lib/format";

type Entry =
  | { kind: "amendment"; at: string; amendment: Amendment }
  | { kind: "decision"; at: string; decision: PlanDecision };

// The session's audit trail (SF-04, ADR 0046 D8, ADR 0052 D11): every amendment and
// every approval or rejection, in the order they happened (ADR 0066).
export function AuditTrail({
  amendments,
  decisions,
}: {
  amendments: Amendment[];
  decisions: PlanDecision[];
}) {
  const entries: Entry[] = [
    ...amendments.map((amendment) => ({
      kind: "amendment" as const,
      at: amendment.amended_at,
      amendment,
    })),
    ...decisions.map((decision) => ({
      kind: "decision" as const,
      at: decision.decided_at,
      decision,
    })),
  ].sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
  if (entries.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Audit trail</CardTitle>
      </CardHeader>
      <CardContent>
        <ol aria-label="Audit trail" className="flex flex-col gap-2 text-sm">
          {entries.map((entry, index) => (
            <li key={index} className="flex flex-wrap items-baseline gap-2">
              <time
                dateTime={entry.at}
                className="text-muted-foreground w-44 shrink-0 tabular-nums"
              >
                {formatDateTime(entry.at)}
              </time>
              {entry.kind === "amendment" ? (
                <AmendmentEntry amendment={entry.amendment} />
              ) : (
                <DecisionEntry decision={entry.decision} />
              )}
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}

function AmendmentEntry({ amendment }: { amendment: Amendment }) {
  return (
    <span className="flex flex-wrap items-baseline gap-2">
      <span>
        Amended plan revision {amendment.amends_revision}: “{amendment.text}”
      </span>
      {amendment.relaxation && (
        <Badge variant="outline">Relaxation accepted</Badge>
      )}
    </span>
  );
}

function DecisionEntry({ decision }: { decision: PlanDecision }) {
  const revision = `plan revision ${decision.revision_number}`;
  return (
    <span>
      {decision.decision === "approved"
        ? `Approved ${revision}`
        : `Rejected ${revision}: ${decision.reason ?? ""}`}
    </span>
  );
}
