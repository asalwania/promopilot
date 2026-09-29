import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { HealthStatus } from "@/components/health-status";

describe("HealthStatus", () => {
  it("shows the API as healthy with its version and checks", () => {
    render(
      <HealthStatus
        result={{
          reachable: true,
          health: {
            status: "ok",
            version: "0.1.0",
            checks: { database: "ok", model_registry: "ok" },
            llm: { mode: "replay", provider: "replay", model: null },
          },
        }}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent("API healthy");
    expect(screen.getByText("v0.1.0")).toBeInTheDocument();
    expect(screen.getByText("database")).toBeInTheDocument();
    expect(screen.getByText("model_registry")).toBeInTheDocument();
  });

  it("shows the API as degraded when a dependency check fails", () => {
    render(
      <HealthStatus
        result={{
          reachable: true,
          health: {
            status: "degraded",
            version: "0.1.0",
            checks: { database: "error", model_registry: "missing" },
            llm: { mode: "replay", provider: "replay", model: null },
          },
        }}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent("API degraded");
    expect(screen.getByText("error")).toBeInTheDocument();
    expect(screen.getByText("missing")).toBeInTheDocument();
  });

  it("shows the API as unreachable with the reason", () => {
    render(
      <HealthStatus result={{ reachable: false, reason: "fetch failed" }} />,
    );

    expect(screen.getByRole("status")).toHaveTextContent("API unreachable");
    expect(screen.getByText("fetch failed")).toBeInTheDocument();
  });
});
