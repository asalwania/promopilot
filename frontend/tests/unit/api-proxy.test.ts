import { describe, expect, it } from "vitest";

import { proxyToApi } from "@/lib/api/proxy";

type Forwarded = { url: string; method: string; body: string };

function recordingFetch(response: Response) {
  const calls: Forwarded[] = [];
  const fetchImpl: typeof fetch = async (input, init) => {
    const request = new Request(input, init);
    calls.push({
      url: request.url,
      method: request.method,
      body: await request.text(),
    });
    return response;
  };
  return { calls, fetchImpl };
}

describe("proxyToApi", () => {
  it("forwards the same path and query string to the API origin", async () => {
    const { calls, fetchImpl } = recordingFetch(new Response("{}"));

    await proxyToApi(
      new Request("http://web:3000/api/sessions/abc?revision=2"),
      "http://api:8000",
      fetchImpl,
    );

    expect(calls[0].url).toBe("http://api:8000/api/sessions/abc?revision=2");
  });

  it("forwards the method and request body", async () => {
    const { calls, fetchImpl } = recordingFetch(new Response("{}"));

    await proxyToApi(
      new Request("http://web:3000/api/sessions", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ brief: "Diwali push" }),
      }),
      "http://api:8000",
      fetchImpl,
    );

    expect(calls[0].method).toBe("POST");
    expect(JSON.parse(calls[0].body)).toEqual({ brief: "Diwali push" });
  });

  it("returns the API status code and body", async () => {
    const { fetchImpl } = recordingFetch(
      new Response(JSON.stringify({ detail: "not found" }), {
        status: 404,
        headers: { "content-type": "application/json" },
      }),
    );

    const response = await proxyToApi(
      new Request("http://web:3000/api/sessions/missing"),
      "http://api:8000",
      fetchImpl,
    );

    expect(response.status).toBe(404);
    expect(response.headers.get("content-type")).toBe("application/json");
    expect(await response.json()).toEqual({ detail: "not found" });
  });

  it("streams the response body chunk by chunk without buffering it", async () => {
    let sendNext!: (chunk: string) => void;
    const upstream = new ReadableStream<Uint8Array>({
      start(controller) {
        const encoder = new TextEncoder();
        sendNext = (chunk) => controller.enqueue(encoder.encode(chunk));
      },
    });
    const { fetchImpl } = recordingFetch(
      new Response(upstream, {
        headers: { "content-type": "text/event-stream" },
      }),
    );

    const response = await proxyToApi(
      new Request("http://web:3000/api/sessions/abc/events"),
      "http://api:8000",
      fetchImpl,
    );
    sendNext("data: first\n\n");
    const reader = response.body!.getReader();
    const first = await reader.read();

    expect(new TextDecoder().decode(first.value)).toBe("data: first\n\n");
    expect(response.headers.get("content-type")).toBe("text/event-stream");
    await reader.cancel();
  });

  it("marks an SSE stream so nothing between the API and the browser buffers it", async () => {
    const { fetchImpl } = recordingFetch(
      new Response("data: {}\n\n", {
        headers: {
          "content-type": "text/event-stream; charset=utf-8",
          "cache-control": "no-cache",
          "x-accel-buffering": "no",
        },
      }),
    );

    const response = await proxyToApi(
      new Request("http://web:3000/api/sessions/abc/events"),
      "http://api:8000",
      fetchImpl,
    );

    // no-transform keeps Next's gzip (and any other proxy) from holding events back.
    expect(response.headers.get("cache-control")).toBe(
      "no-cache, no-transform",
    );
    expect(response.headers.get("x-accel-buffering")).toBe("no");
  });

  it("leaves other responses' caching headers alone", async () => {
    const { fetchImpl } = recordingFetch(
      new Response("{}", {
        headers: {
          "content-type": "application/json",
          "cache-control": "max-age=60",
        },
      }),
    );

    const response = await proxyToApi(
      new Request("http://web:3000/api/health"),
      "http://api:8000",
      fetchImpl,
    );

    expect(response.headers.get("cache-control")).toBe("max-age=60");
    expect(response.headers.get("x-accel-buffering")).toBeNull();
  });

  it("forwards Last-Event-ID so a reconnecting stream resumes", async () => {
    const seen: string[] = [];
    const fetchImpl: typeof fetch = async (input, init) => {
      seen.push(new Request(input, init).headers.get("last-event-id") ?? "");
      return new Response("", {
        headers: { "content-type": "text/event-stream" },
      });
    };

    await proxyToApi(
      new Request("http://web:3000/api/sessions/abc/events", {
        headers: { "Last-Event-ID": "42" },
      }),
      "http://api:8000",
      fetchImpl,
    );

    expect(seen).toEqual(["42"]);
  });

  it("aborts the API request when the browser goes away", async () => {
    let upstreamSignal: AbortSignal | undefined;
    const fetchImpl: typeof fetch = async (_input, init) => {
      upstreamSignal = init?.signal ?? undefined;
      return new Response("", {
        headers: { "content-type": "text/event-stream" },
      });
    };
    const browser = new AbortController();

    await proxyToApi(
      new Request("http://web:3000/api/sessions/abc/events", {
        signal: browser.signal,
      }),
      "http://api:8000",
      fetchImpl,
    );
    browser.abort();

    expect(upstreamSignal?.aborted).toBe(true);
  });

  it("answers 502 when the API cannot be reached", async () => {
    const failingFetch: typeof fetch = async () => {
      throw new TypeError("fetch failed");
    };

    const response = await proxyToApi(
      new Request("http://web:3000/api/health"),
      "http://api:8000",
      failingFetch,
    );

    expect(response.status).toBe(502);
    expect(await response.json()).toEqual({ detail: "API unreachable" });
  });
});
