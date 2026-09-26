"use client";

import { useQuery } from "@tanstack/react-query";

import { SessionDetails } from "@/components/session-details";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getSession, SessionLoadError } from "@/lib/api/sessions";

const POLL_INTERVAL_MS = 1000;
const MAX_RETRIES = 2;

export function SessionView({ sessionId }: { sessionId: string }) {
  const query = useQuery({
    queryKey: ["session", sessionId],
    queryFn: () => getSession(sessionId),
    // Poll only while the planner runs and the API answers; every other status
    // is settled for E3, and a failed read waits for the manager's Retry.
    refetchInterval: ({ state }) =>
      state.status !== "error" && state.data?.status === "planning"
        ? POLL_INTERVAL_MS
        : false,
    retry: (failureCount, error) =>
      !isNotFound(error) && failureCount < MAX_RETRIES,
  });

  if (isNotFound(query.error)) {
    return <Notice title="Session not found" />;
  }
  if (query.error) {
    return (
      <Notice title="Couldn't load the session">
        <CardContent className="flex items-center justify-between gap-4">
          <p className="text-muted-foreground text-sm">{query.error.message}</p>
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
  }
  if (query.data) return <SessionDetails session={query.data} />;
  return <Notice title="Loading session…" />;
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
