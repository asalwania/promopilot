"use client";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { ModelRegistry } from "@/components/model-registry";
import { ReferenceId } from "@/components/error-message";
import { RetrainPanel } from "@/components/retrain-panel";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  listModels,
  MODELS_QUERY_KEY,
  type ModelEntry,
} from "@/lib/api/models";
import { referenceIdOf } from "@/lib/api/reason";

const MAX_RETRIES = 2;

// Loads the registry when the page opens and after our own retrain; it does
// not poll (ADR 0030).
export function ModelsView() {
  const query = useQuery({
    queryKey: MODELS_QUERY_KEY,
    queryFn: () => listModels(),
    retry: MAX_RETRIES,
  });

  return (
    <div className="flex w-full flex-col gap-6">
      <RetrainPanel />
      <Registry query={query} />
    </div>
  );
}

function Registry({ query }: { query: UseQueryResult<ModelEntry[]> }) {
  if (query.error) {
    return (
      <Notice title="Couldn't load models">
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
  }
  if (query.data) return <ModelRegistry models={query.data} />;
  return <Notice title="Loading models…" />;
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
