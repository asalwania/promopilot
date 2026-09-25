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
    const result = await getHealth("http://api:8000", respondWith(healthyBody));

    expect(result).toEqual({ reachable: true, health: healthyBody });
  });

  it("reports the API as unreachable when the network call fails", async () => {
    const failingFetch: typeof fetch = async () => {
      throw new TypeError("fetch failed");
    };

    const result = await getHealth("http://api:8000", failingFetch);

    expect(result).toEqual({ reachable: false, reason: "fetch failed" });
  });

  it("reports the API as unreachable when /health returns a server error", async () => {
    const result = await getHealth(
      "http://api:8000",
      respondWith({ detail: "boom" }, 502),
    );

    expect(result).toEqual({ reachable: false, reason: "HTTP 502" });
  });

  it("reports the API as unreachable when /health breaks the contract", async () => {
    const result = await getHealth(
      "http://api:8000",
      respondWith({ status: "sideways" }),
    );

    expect(result.reachable).toBe(false);
  });
});
