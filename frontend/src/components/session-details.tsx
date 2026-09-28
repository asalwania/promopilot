import { LoaderCircle } from "lucide-react";

import { AssumptionsPanel } from "@/components/assumptions-panel";
import {
  ClarificationForm,
  type SubmitAnswers,
} from "@/components/clarification-form";
import { PlanTable } from "@/components/plan-table";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { UsageMeter } from "@/components/usage-meter";
import type { PlanDecision, Session, SessionStatus } from "@/lib/api/sessions";

const STATUS_LABELS: Record<SessionStatus, string> = {
  planning: "Planning…",
  awaiting_clarification: "Awaiting clarification",
  awaiting_approval: "Awaiting approval",
  approved: "Approved",
  rejected: "Rejected",
  failed: "Planning failed",
};

// What the manager can do from the session page; SessionView owns the calls (ADR 0061).
export type SessionActions = {
  clarify: SubmitAnswers;
};

const NO_ACTIONS: SessionActions = {
  clarify: async () => ({ ok: false, reason: "answers can't be sent here" }),
};

export function SessionDetails({
  session,
  actions = NO_ACTIONS,
}: {
  session: Session;
  actions?: SessionActions;
}) {
  const decision = latestDecision(session);
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
          {decision && <DecisionNote decision={decision} />}
          {session.error && (
            <p role="alert" className="text-destructive text-sm">
              {session.error}
            </p>
          )}
        </CardContent>
      </Card>
      {session.status === "awaiting_clarification" &&
        session.questions.length > 0 && (
          // Keyed by round: a question asked again starts with an empty answer.
          <ClarificationForm
            key={session.clarifications.length}
            questions={session.questions}
            clarifications={session.clarifications}
            onSubmit={actions.clarify}
          />
        )}
      <UsageMeter usage={session.usage} />
      <AssumptionsPanel
        assumptions={session.assumptions}
        status={session.status}
      />
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

// Approve and reject buttons, and the full audit trail, arrive in E10 (ADR 0046).
function latestDecision(session: Session): PlanDecision | undefined {
  return session.decisions.at(-1);
}

function DecisionNote({ decision }: { decision: PlanDecision }) {
  const revision = `Plan revision ${decision.revision_number}`;
  return (
    <p className="text-sm">
      {decision.decision === "approved"
        ? `${revision} was approved.`
        : `${revision} was rejected: ${decision.reason ?? ""}`}
    </p>
  );
}
