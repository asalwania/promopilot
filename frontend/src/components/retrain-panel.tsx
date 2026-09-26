"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { LoaderCircle } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { MODELS_QUERY_KEY, retrainModels } from "@/lib/api/models";

// The API holds the request until the new model is live (ADR 0026) and reports
// no progress, so the panel shows elapsed time, not a percentage (ADR 0030).
export function RetrainPanel() {
  const queryClient = useQueryClient();
  const retrain = useMutation({
    mutationFn: () => retrainModels(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: MODELS_QUERY_KEY });
    },
  });
  const [startedAt, setStartedAt] = useState(0);
  const now = useClock(retrain.isPending);
  const elapsed = Math.max(0, Math.floor((now - startedAt) / 1000));

  function start() {
    setStartedAt(Date.now());
    retrain.mutate();
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-4">
        <p className="text-muted-foreground text-sm">
          Retraining fits the demand model, then the relations model, on the
          loaded sales history, as <code>make train</code> does, and makes the
          new demand version live.
        </p>
        <Button disabled={retrain.isPending} onClick={start}>
          {retrain.isPending ? "Retraining…" : "Retrain"}
        </Button>
      </div>
      {retrain.isPending && (
        <p className="text-muted-foreground flex items-center gap-2 text-sm tabular-nums">
          <LoaderCircle
            role="progressbar"
            aria-label="Retraining in progress"
            className="size-4 animate-spin"
          />
          {formatElapsed(elapsed)} elapsed · usually about a minute
        </p>
      )}
      {retrain.isSuccess && (
        <p role="status" className="text-sm">
          Version {retrain.data.version} is live
        </p>
      )}
      {retrain.isError && (
        <p role="alert" className="text-destructive text-sm">
          Couldn&apos;t retrain: {retrain.error.message}
        </p>
      )}
    </div>
  );
}

// Ticks every second while running, so the elapsed time re-renders.
function useClock(running: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [running]);
  return now;
}

function formatElapsed(seconds: number): string {
  const rest = seconds % 60;
  return `${Math.floor(seconds / 60)}:${rest < 10 ? "0" : ""}${rest}`;
}
