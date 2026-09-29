"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";

import {
  SessionDetails,
  type SessionActions,
} from "@/components/session-details";
import type { CompetitorPrices } from "@/components/competitor-panel";
import { ReferenceId } from "@/components/error-message";
import { TraceTimeline } from "@/components/trace-timeline";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  amendSession,
  approveSession,
  clarifySession,
  getSession,
  rejectSession,
  SessionLoadError,
  simulatePlan,
  type Session,
  type SessionActionResult,
} from "@/lib/api/sessions";
import { referenceIdOf } from "@/lib/api/reason";
import { useCompetitorGaps } from "@/lib/competitor-gaps";
import { useTraceStream } from "@/lib/trace-stream";

const POLL_INTERVAL_MS = 1000;
const MAX_RETRIES = 2;

// The session page's container: it reads the session and its trace stream and
// hands them to presentational components (ADR 0057).
export function SessionView({ sessionId }: { sessionId: string }) {
  const queryClient = useQueryClient();
  const queryKey = ["session", sessionId];
  const query = useQuery({
    queryKey,
    queryFn: () => getSession(sessionId),
    // Poll only while the planner runs and the API answers; every other status
    // waits for the manager, and a failed read waits for the manager's Retry.
    refetchInterval: ({ state }) =>
      state.status !== "error" && state.data?.status === "planning"
        ? POLL_INTERVAL_MS
        : false,
    retry: (failureCount, error) =>
      !isNotFound(error) && failureCount < MAX_RETRIES,
  });

  // Each action's response is the session itself: showing it at once restarts the
  // poll while planning resumes. A conflict means the session moved on, so reload it
  // (ADR 0061 D8–D9, ADR 0066).
  const show = (result: SessionActionResult) => {
    if (result.ok) {
      queryClient.setQueryData(queryKey, result.session);
    } else if (result.conflict) {
      void query.refetch();
    }
    return result;
  };
  const actions: SessionActions = {
    clarify: async (answers) => show(await clarifySession(sessionId, answers)),
    amend: async (amendment) => show(await amendSession(sessionId, amendment)),
    approve: async (revisionNumber) =>
      show(await approveSession(sessionId, revisionNumber)),
    reject: async (revisionNumber, reason) =>
      show(await rejectSession(sessionId, revisionNumber, reason)),
    // A re-simulation answers with the revision's new simulation, which replaces the
    // stored one, so it goes into the cached session's revision (ADR 0068).
    simulate: async (matchProbability) => {
      const result = await simulatePlan(sessionId, matchProbability);
      if (result.ok) {
        queryClient.setQueryData<Session>(queryKey, (session) =>
          session?.plan_revision?.number === result.revisionNumber
            ? {
                ...session,
                plan_revision: {
                  ...session.plan_revision,
                  simulation: result.simulation,
                },
              }
            : session,
        );
      } else if (result.conflict) {
        void query.refetch();
      }
      return result;
    },
  };

  // Undercut callouts on the plan; the plan still shows if the gaps fail (ADR 0060).
  const gaps = useCompetitorGaps(query.data?.planning_request?.as_of_week);

  if (isNotFound(query.error)) {
    return <Notice title="Session not found" />;
  }

  let main: React.ReactNode;
  if (query.error) {
    main = (
      <Notice title="Couldn't load the session">
        <CardContent className="flex items-center justify-between gap-4">
          <p className="text-muted-foreground text-sm">
            {query.error.message}
            <ReferenceId referenceId={referenceIdOf(query.error)} />
          </p>
          <Button
            variant="outline"
            disabled={query.isFetching}
            onClick={() => query.refetch()}
          >
            Retry
          </Button>
        </CardContent>
      </Notice>
    );
  } else if (query.data) {
    main = (
      <SessionDetails
        session={query.data}
        actions={actions}
        competitorGaps={gaps.data?.gaps}
        competitorPrices={competitorPrices(gaps)}
      />
    );
  } else {
    main = <Notice title="Loading session…" />;
  }

  // Left: the live trace (SPEC §11), sticky so it stays in view; main: the session.
  return (
    <div className="grid w-full grid-cols-[minmax(320px,380px)_minmax(0,1fr)] items-start gap-6">
      <div className="sticky top-4 flex max-h-[calc(100vh-2rem)] flex-col">
        <LiveTrace sessionId={sessionId} />
      </div>
      <div className="flex min-w-0 flex-col gap-4">{main}</div>
    </div>
  );
}

function LiveTrace({ sessionId }: { sessionId: string }) {
  const { events, connection, retry } = useTraceStream(sessionId);
  return (
    <TraceTimeline events={events} connection={connection} onRetry={retry} />
  );
}

// The competitor panel's view of the shared gaps query (ADR 0060 D10, ADR 0068).
function competitorPrices(
  gaps: ReturnType<typeof useCompetitorGaps>,
): CompetitorPrices {
  if (gaps.data) return { status: "ready", gaps: gaps.data.gaps };
  if (gaps.error) {
    return {
      status: "error",
      reason: gaps.error.message,
      referenceId: referenceIdOf(gaps.error),
      retry: () => void gaps.refetch(),
    };
  }
  return { status: "loading" };
}

function isNotFound(error: unknown): boolean {
  return error instanceof SessionLoadError && error.notFound;
}

function Notice({
  title,
  children,
}: {
  title: string;
  children?: React.ReactNode;
}) {
  return (
    <Card className="w-full">
      <CardHeader>
        <CardTitle role="status">{title}</CardTitle>
      </CardHeader>
      {children}
    </Card>
  );
}
