import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { HealthPanel } from "@/components/health-panel";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("HealthPanel", () => {
  it("shows a checking state, then the health the proxy returns", async () => {
    vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
      if (String(input) !== "/api/health")
        return new Response(null, { status: 404 });
      return Response.json({
        status: "ok",
        version: "0.1.0",
        checks: { database: "ok", model_registry: "ok" },
        llm: { mode: "replay", provider: "replay", model: null },
      });
    });

    render(<HealthPanel />);

    expect(screen.getByRole("status")).toHaveTextContent("Checking API");
    expect(await screen.findByText("API healthy")).toBeInTheDocument();
  });

  it("shows the API as unreachable when the proxy answers 502", async () => {
    vi.stubGlobal("fetch", async () =>
      Response.json({ detail: "API unreachable" }, { status: 502 }),
    );

    render(<HealthPanel />);

    expect(await screen.findByText("API unreachable")).toBeInTheDocument();
    expect(screen.getByText("HTTP 502")).toBeInTheDocument();
  });
});
