import { LoaderCircle } from "lucide-react";

import { type SubmitAmendment } from "@/components/amend-box";
import { AssumptionsPanel } from "@/components/assumptions-panel";
import { AuditTrail } from "@/components/audit-trail";
import {
  ClarificationForm,
  type SubmitAnswers,
} from "@/components/clarification-form";
import {
  CompetitorPanel,
  type CompetitorPrices,
} from "@/components/competitor-panel";
import { ConstraintChecklist } from "@/components/constraint-checklist";
import {
  InfeasibilityPanel,
  needsRelaxation,
} from "@/components/infeasibility-panel";
import { NotSelectedList } from "@/components/not-selected-list";
import { PlanSummary } from "@/components/plan-summary";
import { RegionPlanTabs } from "@/components/region-plan-tabs";
import {
  ReviewPanel,
  type Approve,
  type Reject,
} from "@/components/review-panel";
import { RevisionDiffView } from "@/components/revision-diff";
import { SimulationPanel, type Simulate } from "@/components/simulation-panel";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { UsageMeter } from "@/components/usage-meter";
import type { CompetitorGap } from "@/lib/api/catalog";
import type { PlanDecision, Session, SessionStatus } from "@/lib/api/sessions";

const STATUS_LABELS: Record<SessionStatus, string> = {
  planning: "Planning…",
  awaiting_clarification: "Awaiting clarification",
  awaiting_approval: "Awaiting approval",
  approved: "Approved",
  rejected: "Rejected",
  failed: "Planning failed",
};

// What the manager can do from the session page; SessionView owns the calls
// (ADR 0061 D12, ADR 0066).
export type SessionActions = {
  clarify: SubmitAnswers;
  amend: SubmitAmendment;
  approve: Approve;
  reject: Reject;
  simulate: Simulate;
};

const cannot = (what: string) => async () => ({
  ok: false as const,
  reason: `${what} can't be sent here`,
});

const NO_ACTIONS: SessionActions = {
  clarify: cannot("answers"),
  amend: cannot("amendments"),
  approve: cannot("approvals"),
  reject: cannot("rejections"),
  simulate: cannot("re-simulations"),
};

export function SessionDetails({
  session,
  actions = NO_ACTIONS,
  competitorGaps,
  competitorPrices,
}: {
  session: Session;
  actions?: Partial<SessionActions>;
  // The KVI gaps at the request's as-of week, for the plan's undercut callouts.
  competitorGaps?: CompetitorGap[];
  // The same gaps with their loading state, for the competitor panel (ADR 0068).
  competitorPrices?: CompetitorPrices;
}) {
  const decision = latestDecision(session);
  const act = { ...NO_ACTIONS, ...actions };
  const revision = session.plan_revision;
  const final = session.status === "approved";
  const replanning = replanningAmendment(session);
  const reviewable =
    session.status === "awaiting_approval" || session.status === "rejected";
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
            {final && <Badge variant="secondary">Final</Badge>}
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          <p className="text-muted-foreground text-sm">{session.brief}</p>
          {decision && <DecisionNote decision={decision} />}
          {final && (
            <p className="text-sm">
              This plan is final: it can no longer be amended, approved or
              rejected.
            </p>
          )}
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
            onSubmit={act.clarify}
          />
        )}
      {reviewable && revision && (
        // Keyed so a new revision, or a decision on this one, starts a fresh review.
        <ReviewPanel
          key={`${revision.number}-${session.status}`}
          revision={revision}
          status={session.status as "awaiting_approval" | "rejected"}
          onAmend={act.amend}
          onApprove={act.approve}
          onReject={act.reject}
        />
      )}
      <UsageMeter usage={session.usage} />
      <AssumptionsPanel
        assumptions={session.assumptions}
        status={session.status}
      />
      {revision && (
        <Card>
          <CardHeader>
            <CardTitle>Plan revision {revision.number}</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            {replanning && (
              <p className="text-muted-foreground text-sm">
                Re-planning after your amendment “{replanning.text}”: showing
                plan revision {revision.number} until the new one is ready.
              </p>
            )}
            {needsRelaxation(revision) && (
              // Keyed so a new revision starts with no pending accept (ADR 0067);
              // the prefix keeps its key apart from the region tabs', a sibling.
              <InfeasibilityPanel
                key={`relaxation-${revision.number}`}
                revision={revision}
                canAccept={reviewable}
                onAcceptRelaxation={() => act.amend({ acceptRelaxation: true })}
              />
            )}
            {revision.explanation && (
              <PlanSummary explanation={revision.explanation} />
            )}
            {revision.diff && (
              <RevisionDiffView
                diff={revision.diff}
                explanation={revision.explanation}
                amendment={session.amendments.findLast(
                  (amendment) =>
                    amendment.amends_revision === revision.diff?.from_revision,
                )}
              />
            )}
            {revision.lines.length > 0 ? (
              // Keyed so a new revision opens on its first region (ADR 0066).
              <RegionPlanTabs
                key={revision.number}
                revision={revision}
                regions={session.planning_request?.scope.regions ?? []}
                competitorGaps={competitorGaps}
              />
            ) : (
              revision.solver_status !== "INFEASIBLE" && (
                <p className="text-muted-foreground text-sm">
                  No promo option pays for itself within the brief&apos;s
                  constraints.
                </p>
              )
            )}
          </CardContent>
        </Card>
      )}
      {revision && (
        <ConstraintChecklist
          revision={revision}
          request={session.planning_request}
        />
      )}
      {revision && <NotSelectedList options={revision.not_selected} />}
      {/* Competitor handling and risk (F-08, F-09); only a plan awaiting a decision
          can be re-simulated (ADR 0066, ADR 0068). */}
      {revision && session.planning_request && competitorPrices && (
        <CompetitorPanel
          prices={competitorPrices}
          request={session.planning_request}
          revision={revision}
        />
      )}
      {revision && (
        <SimulationPanel
          key={revision.number}
          revisionNumber={revision.number}
          simulation={revision.simulation}
          onSimulate={reviewable ? act.simulate : undefined}
        />
      )}
      <AuditTrail
        amendments={session.amendments}
        decisions={session.decisions}
      />
    </div>
  );
}

// The amendment being planned, while the read model still holds the revision it
// amended (ADR 0052 D10).
function replanningAmendment(session: Session) {
  const amendment = session.amendments.at(-1);
  return session.status === "planning" &&
    amendment &&
    amendment.amends_revision === session.plan_revision?.number
    ? amendment
    : undefined;
}

// The latest decision, in the status card; the audit trail lists them all.
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
