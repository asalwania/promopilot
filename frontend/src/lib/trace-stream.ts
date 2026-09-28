"use client";

import { useCallback, useEffect, useState } from "react";

import { type TraceEvent, traceEventSchema } from "@/lib/api/trace";

export type TraceConnection =
  "connecting" | "live" | "reconnecting" | "ended" | "error";

// The part of the browser's EventSource the stream uses, so tests can script one.
export type TraceSource = {
  readonly readyState: number;
  onopen: ((event: Event) => void) | null;
  onmessage: ((event: MessageEvent) => void) | null;
  onerror: ((event: Event) => void) | null;
  addEventListener(type: "end", listener: (event: MessageEvent) => void): void;
  close(): void;
};

export type OpenTraceSource = (url: string) => TraceSource;

// How long to wait before reopening a stream the browser gave up on (ADR 0057).
export const RECONNECT_DELAYS_MS = [1000, 2000, 4000, 8000, 16_000];

const CLOSED = 2;

const openEventSource: OpenTraceSource = (url) => new EventSource(url);

// Events arrive in id order; a replay after a reopen repeats ids already seen.
export function mergeTraceEvent(
  events: TraceEvent[],
  event: TraceEvent,
): TraceEvent[] {
  const last = events.at(-1);
  return last && event.id <= last.id ? events : [...events, event];
}

function parseTraceEvent(data: string): TraceEvent | null {
  let json: unknown;
  try {
    json = JSON.parse(data);
  } catch {
    json = undefined;
  }
  const parsed = traceEventSchema.safeParse(json);
  if (parsed.success) return parsed.data;
  console.warn("Skipped a malformed trace event", data);
  return null;
}

// A session's trace events, live from the proxied SSE stream (ADR 0047, ADR 0057).
// The browser reconnects after a network blip with Last-Event-ID on its own; a
// source it gives up on (an HTTP error) is reopened with backoff, and its replay
// from the start is deduplicated by event id. The stream closes on `end`.
export function useTraceStream(
  sessionId: string,
  { open = openEventSource }: { open?: OpenTraceSource } = {},
) {
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [connection, setConnection] = useState<TraceConnection>("connecting");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const url = `/api/sessions/${encodeURIComponent(sessionId)}/events`;
    let source: TraceSource | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let failures = 0;
    let stopped = false;

    const connect = () => {
      const current = open(url);
      source = current;
      current.onopen = () => {
        failures = 0;
        setConnection("live");
      };
      current.onmessage = (message) => {
        const event = parseTraceEvent(String(message.data));
        if (event) setEvents((seen) => mergeTraceEvent(seen, event));
      };
      current.addEventListener("end", () => {
        stopped = true;
        current.close();
        setConnection("ended");
      });
      current.onerror = () => {
        if (stopped) return;
        if (current.readyState !== CLOSED) {
          setConnection("reconnecting");
          return;
        }
        current.close();
        if (failures >= RECONNECT_DELAYS_MS.length) {
          setConnection("error");
          return;
        }
        setConnection("reconnecting");
        timer = setTimeout(connect, RECONNECT_DELAYS_MS[failures]);
        failures += 1;
      };
    };

    connect();
    return () => {
      stopped = true;
      clearTimeout(timer);
      source?.close();
    };
  }, [sessionId, open, attempt]);

  const retry = useCallback(() => {
    setConnection("connecting");
    setAttempt((count) => count + 1);
  }, []);

  return { events, connection, retry };
}
