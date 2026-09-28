// Forwards a same-origin `/api/*` request to the API (ADR 0001) so the browser
// never needs CORS or a second public URL. Bodies stream both ways, so the same
// proxy carries a session's SSE trace stream (ADR 0047): the browser's
// Last-Event-ID goes up with the other headers, and closing the stream in the
// browser aborts the API request.

// Node's fetch has already decoded the body, so these would describe bytes the
// browser never receives.
const DROPPED_RESPONSE_HEADERS = ["content-encoding", "content-length"];

export async function proxyToApi(
  request: Request,
  apiUrl: string,
  fetchImpl: typeof fetch = fetch,
): Promise<Response> {
  const { pathname, search } = new URL(request.url);
  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  const headers = new Headers(request.headers);
  headers.delete("host");

  let upstream: Response;
  try {
    upstream = await fetchImpl(`${apiUrl}${pathname}${search}`, {
      method: request.method,
      headers,
      body: hasBody ? request.body : undefined,
      signal: request.signal,
      cache: "no-store",
      // Required by Node's fetch to send a streamed request body.
      ...(hasBody ? { duplex: "half" } : {}),
    } as RequestInit);
  } catch {
    return Response.json({ detail: "API unreachable" }, { status: 502 });
  }

  const responseHeaders = new Headers(upstream.headers);
  for (const name of DROPPED_RESPONSE_HEADERS) responseHeaders.delete(name);
  if (isEventStream(responseHeaders)) {
    // Next compresses responses in production and would hold events back until
    // a compression block fills; no-transform makes it (and any other proxy)
    // pass them through as they come.
    responseHeaders.set("cache-control", "no-cache, no-transform");
    responseHeaders.set("x-accel-buffering", "no");
  }
  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders,
  });
}

function isEventStream(headers: Headers): boolean {
  return (headers.get("content-type") ?? "").startsWith("text/event-stream");
}
