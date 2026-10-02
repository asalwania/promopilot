"use client";

import {
  Coins,
  MessageCircleQuestionMark,
  Signpost,
  TriangleAlert,
  Wrench,
} from "lucide-react";
import { useEffect, useRef } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { TraceEvent, TracePayload } from "@/lib/api/trace";
import {
  formatClockTime,
  formatDuration,
  formatPrice,
  formatTokens,
} from "@/lib/format";
import type { TraceConnection } from "@/lib/trace-stream";
import { cn } from "@/lib/utils";

type Payload<K extends TracePayload["kind"]> = Extract<
  TracePayload,
  { kind: K }
>;

// One run of a graph node: from its start to its finish, with what it did between.
type NodeRun = {
  key: number;
  node: string | null;
  attempt: number;
  finished: Payload<"node_finished"> | null;
  steps: TraceEvent[];
};

const NODE_LABELS: Record<string, string> = {
  context: "Context agent",
  clarify: "Clarify",
  planner: "Planner",
  critic: "Critic",
  explainer: "Explainer",
  approval: "Approval",
  done: "Done",
};

const CONNECTION_LABELS: Record<TraceConnection, string> = {
  connecting: "Connecting…",
  live: "Live",
  reconnecting: "Reconnecting…",
  ended: "Final",
  error: "Disconnected",
};

const EMPTY_NOTES: Partial<Record<TraceConnection, string>> = {
  connecting: "Connecting to the trace…",
  live: "Waiting for the agent's first step…",
  reconnecting: "Connecting to the trace…",
  ended: "No trace was recorded for this session.",
};

// Pixels from the bottom that still count as following the newest event.
const FOLLOW_SLACK_PX = 24;

// The agent at work (SF-01): every node run with its tool calls, decisions,
// findings, questions and LLM calls, live from the trace stream (ADR 0057).
export function TraceTimeline({
  events,
  connection,
  onRetry,
}: {
  events: TraceEvent[];
  connection: TraceConnection;
  onRetry: () => void;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  const following = useRef(true);
  const runs = groupByNodeRun(events);

  // Follow the newest event, unless the manager has scrolled up to read.
  useEffect(() => {
    const element = scroller.current;
    if (element && following.current) element.scrollTop = element.scrollHeight;
  }, [events.length]);

  return (
    <Card
      role="region"
      aria-labelledby="trace-title"
      size="sm"
      className="max-h-full"
    >
      <CardHeader>
        <CardTitle id="trace-title">Agent trace</CardTitle>
        <CardAction>
          <Badge
            aria-live="polite"
            variant={connection === "error" ? "destructive" : "outline"}
          >
            {CONNECTION_LABELS[connection]}
          </Badge>
        </CardAction>
      </CardHeader>
      <CardContent
        ref={scroller}
        onScroll={(event) => {
          const element = event.currentTarget;
          following.current =
            element.scrollHeight - element.scrollTop - element.clientHeight <
            FOLLOW_SLACK_PX;
        }}
        className="flex min-h-0 flex-col gap-3 overflow-y-auto"
      >
        {connection === "error" && (
          <div
            role="alert"
            className="text-destructive flex items-center justify-between gap-2 text-sm"
          >
            Lost the trace stream.
            <Button variant="outline" size="sm" onClick={onRetry}>
              Retry
            </Button>
          </div>
        )}
        {connection === "reconnecting" && runs.length > 0 && (
          <p className="text-muted-foreground text-xs">
            The trace continues where it left off.
          </p>
        )}
        {runs.length === 0 ? (
          EMPTY_NOTES[connection] && (
            <p className="text-muted-foreground text-sm">
              {EMPTY_NOTES[connection]}
            </p>
          )
        ) : (
          <ol
            aria-label="Trace timeline"
            className="before:bg-primary/25 relative flex flex-col gap-4 before:absolute before:top-2 before:bottom-2 before:left-[5px] before:w-px"
          >
            {runs.map((run) => (
              <NodeRunEntry key={run.key} run={run} />
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}

function groupByNodeRun(events: TraceEvent[]): NodeRun[] {
  const runs: NodeRun[] = [];
  const attempts = new Map<string | null, number>();
  const start = (event: TraceEvent): NodeRun => {
    const attempt = (attempts.get(event.node) ?? 0) + 1;
    attempts.set(event.node, attempt);
    const run = {
      key: event.id,
      node: event.node,
      attempt,
      finished: null,
      steps: [],
    };
    runs.push(run);
    return run;
  };
  for (const event of events) {
    const { payload } = event;
    if (payload.kind === "node_started") {
      start(event);
      continue;
    }
    // Events only come from inside a node; the run it belongs to is the latest one
    // of that node still open, or a new one if its start is missing.
    const open = runs.findLast(
      (run) => run.node === event.node && run.finished === null,
    );
    const run = open ?? start(event);
    if (payload.kind === "node_finished") run.finished = payload;
    else run.steps.push(event);
  }
  return runs;
}

function nodeLabel(node: string | null): string {
  if (node === null) return "Session";
  return NODE_LABELS[node] ?? node.charAt(0).toUpperCase() + node.slice(1);
}

function NodeRunEntry({ run }: { run: NodeRun }) {
  const label =
    run.attempt > 1
      ? `${nodeLabel(run.node)} · attempt ${run.attempt}`
      : nodeLabel(run.node);
  const { finished } = run;
  return (
    <li data-run="" className="relative flex flex-col gap-1.5 pl-6">
      <span
        aria-hidden
        className={cn(
          "ring-card absolute top-[5px] left-0 size-[11px] rounded-full ring-4",
          finished === null
            ? "bg-primary animate-pulse"
            : finished.outcome === "failed"
              ? "bg-destructive"
              : "bg-primary",
        )}
      />
      <h3 className="flex items-center gap-2 text-sm font-semibold">
        <span>{label}</span>
        <OutcomeBadge finished={finished} />
        {finished && (
          <span className="text-muted-foreground text-xs font-normal tabular-nums">
            {formatDuration(finished.duration_ms)}
          </span>
        )}
      </h3>
      {finished?.outcome === "failed" && finished.error && (
        <p role="alert" className="text-destructive text-xs">
          {finished.error}
        </p>
      )}
      {run.steps.length > 0 && (
        <ul className="border-border flex flex-col gap-1.5 border-l pl-3">
          {run.steps.map((event) => (
            <li
              key={event.id}
              title={formatClockTime(event.at)}
              className="flex flex-col gap-1 text-xs"
            >
              <Step payload={event.payload} />
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

function OutcomeBadge({
  finished,
}: {
  finished: Payload<"node_finished"> | null;
}) {
  if (finished === null) return <Badge variant="secondary">Running</Badge>;
  switch (finished.outcome) {
    case "completed":
      return <Badge className="bg-success-muted text-success">Done</Badge>;
    case "interrupted":
      return <Badge variant="secondary">Paused</Badge>;
    case "failed":
      return <Badge variant="destructive">Failed</Badge>;
  }
}

function Step({ payload }: { payload: TracePayload }) {
  switch (payload.kind) {
    case "tool_called":
      return <ToolCall call={payload} />;
    case "decision":
      return (
        <Line icon={<Signpost />}>
          <Badge variant="secondary">{payload.decision}</Badge>
          <span>{payload.summary}</span>
        </Line>
      );
    case "finding":
      return (
        <Line icon={<TriangleAlert />}>
          <Badge variant="outline">{payload.source}</Badge>
          <Badge variant="outline">{payload.code}</Badge>
          <span>{payload.message}</span>
        </Line>
      );
    case "clarification":
      return (
        <Line icon={<MessageCircleQuestionMark />}>
          <span className="flex flex-col gap-0.5">
            <span className="font-medium">Asked for clarification</span>
            <ul className="list-disc pl-4">
              {payload.questions.map((question) => (
                <li key={question}>{question}</li>
              ))}
            </ul>
          </span>
        </Line>
      );
    case "token_usage":
      return (
        <Line icon={<Coins />}>
          <span className="text-muted-foreground tabular-nums">
            {`${payload.model} · ${formatTokens(payload.input_tokens)} in / ${formatTokens(payload.output_tokens)} out · ${payload.cost_inr === null ? "no price" : formatPrice(payload.cost_inr)}`}
          </span>
        </Line>
      );
    // A run's start and finish are its heading.
    case "node_started":
    case "node_finished":
      return null;
  }
}

function ToolCall({ call }: { call: Payload<"tool_called"> }) {
  return (
    <>
      <Line icon={<Wrench />}>
        <code className="font-mono">{call.tool}</code>
        <Badge variant={call.ok ? "outline" : "destructive"}>
          {call.ok ? "ok" : `error: ${call.error_code ?? "failed"}`}
        </Badge>
      </Line>
      <details className="pl-5">
        <summary className="text-muted-foreground cursor-pointer">
          Arguments and result
        </summary>
        <pre className="bg-muted mt-1 overflow-x-auto rounded-lg p-2.5 text-[11px]">
          {JSON.stringify(call.arguments, null, 2)}
        </pre>
        <pre className="bg-muted mt-1 overflow-x-auto rounded-lg p-2.5 text-[11px]">
          {JSON.stringify(call.result_summary, null, 2)}
        </pre>
      </details>
    </>
  );
}

function Line({
  icon,
  children,
}: {
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      <span aria-hidden className="text-muted-foreground [&>svg]:size-3.5">
        {icon}
      </span>
      {children}
    </span>
  );
}
