import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mergeTraceEvent, useTraceStream } from "@/lib/trace-stream";

import { FakeEventSource } from "./fixtures/fake-event-source";
import { SESSION_ID } from "./fixtures/sessions";
import { traceEvent, traceEvents } from "./fixtures/trace";

const open = (url: string) => new FakeEventSource(url);

function renderStream() {
  return renderHook(() => useTraceStream(SESSION_ID, { open }));
}

const ids = (events: { id: number }[]) => events.map((event) => event.id);

beforeEach(() => {
  FakeEventSource.reset();
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("mergeTraceEvent", () => {
  it("appends a newer event and drops one already seen", () => {
    const [first, second] = traceEvents;
    const once = mergeTraceEvent([first], second);
    expect(ids(once)).toEqual([1, 2]);
    expect(mergeTraceEvent(once, first)).toBe(once);
    expect(mergeTraceEvent(once, second)).toBe(once);
  });
});

describe("useTraceStream", () => {
  it("opens the session's proxied event stream and collects its events live", () => {
    const { result } = renderStream();
    const source = FakeEventSource.latest();

    expect(source.url).toBe(`/api/sessions/${SESSION_ID}/events`);
    expect(result.current.connection).toBe("connecting");

    act(() => {
      source.open();
      traceEvents.slice(0, 3).forEach((event) => source.send(event));
    });

    expect(result.current.connection).toBe("live");
    expect(ids(result.current.events)).toEqual([1, 2, 3]);
  });

  it("continues after a network blip without duplicates", () => {
    const { result } = renderStream();
    const source = FakeEventSource.latest();
    act(() => {
      source.open();
      traceEvents.slice(0, 3).forEach((event) => source.send(event));
      source.drop();
    });
    expect(result.current.connection).toBe("reconnecting");

    // The browser resumes after Last-Event-ID; an overlapping event is dropped.
    act(() => {
      source.open();
      traceEvents.slice(2, 5).forEach((event) => source.send(event));
    });

    expect(FakeEventSource.instances).toHaveLength(1);
    expect(result.current.connection).toBe("live");
    expect(ids(result.current.events)).toEqual([1, 2, 3, 4, 5]);
  });

  it("reopens a source the browser gave up on, and the replay adds no duplicates", () => {
    const { result } = renderStream();
    const first = FakeEventSource.latest();
    act(() => {
      first.open();
      traceEvents.slice(0, 3).forEach((event) => first.send(event));
      first.fail();
    });
    expect(first.closed).toBe(true);
    expect(result.current.connection).toBe("reconnecting");

    act(() => vi.advanceTimersByTime(1000));
    const second = FakeEventSource.latest();
    expect(second).not.toBe(first);

    // A new EventSource cannot send Last-Event-ID, so it replays from the start.
    act(() => {
      second.open();
      traceEvents.slice(0, 5).forEach((event) => second.send(event));
    });

    expect(result.current.connection).toBe("live");
    expect(ids(result.current.events)).toEqual([1, 2, 3, 4, 5]);
  });

  it("backs off, then reports an error that Retry recovers from", () => {
    const { result } = renderStream();
    for (const delay of [1000, 2000, 4000, 8000, 16_000]) {
      act(() => FakeEventSource.latest().fail());
      expect(result.current.connection).toBe("reconnecting");
      const opened = FakeEventSource.instances.length;
      act(() => vi.advanceTimersByTime(delay - 1));
      expect(FakeEventSource.instances).toHaveLength(opened);
      act(() => vi.advanceTimersByTime(1));
      expect(FakeEventSource.instances).toHaveLength(opened + 1);
    }

    act(() => FakeEventSource.latest().fail());
    expect(result.current.connection).toBe("error");
    act(() => vi.advanceTimersByTime(60_000));
    expect(FakeEventSource.instances).toHaveLength(6);

    act(() => result.current.retry());
    expect(FakeEventSource.instances).toHaveLength(7);
    expect(result.current.connection).toBe("connecting");
    act(() => FakeEventSource.latest().open());
    expect(result.current.connection).toBe("live");
  });

  it("restarts the backoff once a reopened stream is live", () => {
    const { result } = renderStream();
    act(() => FakeEventSource.latest().fail());
    act(() => vi.advanceTimersByTime(1000));
    act(() => {
      FakeEventSource.latest().open();
      FakeEventSource.latest().fail();
    });
    const opened = FakeEventSource.instances.length;
    act(() => vi.advanceTimersByTime(1000));

    expect(FakeEventSource.instances).toHaveLength(opened + 1);
    expect(result.current.connection).toBe("reconnecting");
  });

  it("closes the stream on its end event", () => {
    const { result } = renderStream();
    const source = FakeEventSource.latest();
    act(() => {
      source.open();
      source.send(traceEvents[0]);
      source.end({ session_id: SESSION_ID, status: "approved" });
    });

    expect(source.closed).toBe(true);
    expect(result.current.connection).toBe("ended");
    act(() => vi.advanceTimersByTime(60_000));
    expect(FakeEventSource.instances).toHaveLength(1);
  });

  it("skips a malformed event with a warning", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { result } = renderStream();
    const source = FakeEventSource.latest();
    act(() => {
      source.open();
      source.sendRaw("not json", "1");
      source.sendRaw(JSON.stringify({ id: 2, payload: { kind: "?" } }), "2");
      source.send(traceEvent(3, "context", { kind: "node_started" }));
    });

    expect(ids(result.current.events)).toEqual([3]);
    expect(warn).toHaveBeenCalledTimes(2);
  });

  it("closes the stream when the page goes away", () => {
    const { unmount } = renderStream();
    const source = FakeEventSource.latest();
    act(() => source.fail());

    unmount();
    act(() => vi.advanceTimersByTime(60_000));

    expect(FakeEventSource.instances).toHaveLength(1);
    expect(source.closed).toBe(true);
  });
});
