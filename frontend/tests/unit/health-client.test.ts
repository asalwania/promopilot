import { describe, expect, it } from "vitest";

import { getHealth } from "@/lib/api/health";

function respondWith(body: unknown, status = 200): typeof fetch {
  return async () =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    });
}

const healthyBody = {
  status: "ok",
  version: "0.1.0",
  checks: { database: "ok", model_registry: "not_initialised" },
};

describe("getHealth", () => {
  it("returns the API health when /health answers", async () => {
    const result = await getHealth(respondWith(healthyBody));

    expect(result).toEqual({ reachable: true, health: healthyBody });
  });

  it("asks the same-origin proxy, never the API origin", async () => {
    const requested: string[] = [];
    const fetchImpl: typeof fetch = async (input) => {
      requested.push(String(input));
      return new Response(JSON.stringify(healthyBody));
    };

    await getHealth(fetchImpl);

    expect(requested).toEqual(["/api/health"]);
  });

  it("reports the API as unreachable when the network call fails", async () => {
    const failingFetch: typeof fetch = async () => {
      throw new TypeError("fetch failed");
    };

    const result = await getHealth(failingFetch);

    expect(result).toEqual({ reachable: false, reason: "fetch failed" });
  });

  it("reports the API as unreachable when /health returns a server error", async () => {
    const result = await getHealth(respondWith({ detail: "boom" }, 502));

    expect(result).toEqual({ reachable: false, reason: "HTTP 502" });
  });

  it("reports the API as unreachable when /health breaks the contract", async () => {
    const result = await getHealth(respondWith({ status: "sideways" }));

    expect(result.reachable).toBe(false);
  });
});
