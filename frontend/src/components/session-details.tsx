import { LoaderCircle } from "lucide-react";

import { PlanTable } from "@/components/plan-table";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type {
  PlanningRequest,
  Session,
  SessionStatus,
} from "@/lib/api/sessions";
import { formatRupees, formatWeek } from "@/lib/format";

const STATUS_LABELS: Record<SessionStatus, string> = {
  planning: "Planning…",
  awaiting_clarification: "Awaiting clarification",
  awaiting_approval: "Awaiting approval",
  approved: "Approved",
  rejected: "Rejected",
  failed: "Planning failed",
};

export function SessionDetails({ session }: { session: Session }) {
  return (
    <div className="flex w-full flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle role="status" className="flex items-center gap-2">
            {session.status === "planning" && (
              <LoaderCircle
                role="progressbar"
                aria-label="Planning in progress"
                className="size-4 animate-spin"
              />
            )}
            {STATUS_LABELS[session.status]}
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          <p className="text-muted-foreground text-sm">{session.brief}</p>
          {session.error && (
            <p role="alert" className="text-destructive text-sm">
              {session.error}
            </p>
          )}
        </CardContent>
      </Card>
      {session.planning_request && (
        <PlanningRequestSummary request={session.planning_request} />
      )}
      {session.plan_revision && (
        <Card>
          <CardHeader>
            <CardTitle>Plan revision {session.plan_revision.number}</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            {/* The relaxation itself is shown in E10 (ADR 0044). */}
            {session.plan_revision.solver_status === "INFEASIBLE" && (
              <p role="alert" className="text-destructive text-sm">
                Infeasible: no plan reaches every clearance target within the
                brief&apos;s constraints.
              </p>
            )}
            {session.plan_revision.lines.length > 0 ? (
              <PlanTable lines={session.plan_revision.lines} />
            ) : (
              session.plan_revision.solver_status !== "INFEASIBLE" && (
                <p className="text-muted-foreground text-sm">
                  No promo option pays for itself within the brief&apos;s
                  constraints.
                </p>
              )
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function PlanningRequestSummary({ request }: { request: PlanningRequest }) {
  const { scope, promo_window } = request;
  const terms: [string, string][] = [
    ["Regions", scope.regions.join(", ")],
    ["Categories", scope.categories.join(", ")],
    [
      "Promo window",
      `${formatWeek(promo_window.start_week)}–${formatWeek(promo_window.end_week)}`,
    ],
    ["Marketing budget", formatRupees(request.marketing_budget)],
  ];
  return (
    <Card role="region" aria-labelledby="planning-request-title">
      <CardHeader>
        <CardTitle id="planning-request-title">Planning request</CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-1 text-sm">
          {terms.map(([term, value]) => (
            <div key={term} className="contents">
              <dt className="text-muted-foreground">{term}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      </CardContent>
    </Card>
  );
}
