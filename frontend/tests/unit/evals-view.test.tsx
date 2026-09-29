import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EvalsView } from "@/components/evals-view";

import recorded from "./fixtures/eval-report.json";

type Answer = () => Response;

function stubEvalsApi(answers: Answer[]) {
  const requested: string[] = [];
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    requested.push(String(input));
    return answers[Math.min(requested.length, answers.length) - 1]();
  });
  return requested;
}

function renderView() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <EvalsView />
    </QueryClientProvider>,
  );
}

const noReport = () =>
  Response.json(
    { detail: "No eval report yet: run `make eval`." },
    { status: 404 },
  );
const unreachable = () =>
  Response.json(
    { detail: "API unreachable", code: "upstream_unreachable" },
    { status: 502, headers: { "x-request-id": "req-7" } },
  );

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("EvalsView", () => {
  it("shows the latest report: provenance, metric cards, scenarios and regret", async () => {
    stubEvalsApi([() => Response.json(recorded)]);

    renderView();

    expect(
      await screen.findByRole("table", { name: "Scenarios" }),
    ).toBeVisible();
    const provenance = screen.getByLabelText("Report provenance");
    expect(provenance).toHaveTextContent("openai (recording)");
    expect(provenance).toHaveTextContent("seed-42 world");
    expect(provenance).toHaveTextContent("8 scenarios × 1 run");
    expect(
      screen.getByRole("article", { name: "Constraint satisfaction" }),
    ).toBeVisible();
    expect(
      screen.getByRole("figure", {
        name: "Regret against the best plan, per scored run",
      }),
    ).toBeVisible();
  });

  it("shows a clear empty state before any eval run, without retrying", async () => {
    const requested = stubEvalsApi([noReport]);

    renderView();

    expect(await screen.findByRole("status")).toHaveTextContent(
      "No eval report yet",
    );
    expect(
      screen.getByText("No eval report yet: run `make eval`."),
    ).toBeVisible();
    expect(screen.getByText(/make eval SMOKE=1/)).toBeVisible();
    await act(() => vi.advanceTimersByTimeAsync(10_000));
    expect(requested).toEqual(["/api/evals/latest"]);
  });

  it("gives up after retries with the reason and a Retry button that recovers", async () => {
    stubEvalsApi([
      unreachable,
      unreachable,
      unreachable,
      () => Response.json(recorded),
    ]);

    renderView();
    await act(() => vi.advanceTimersByTimeAsync(10_000));

    expect(screen.getByRole("status")).toHaveTextContent(
      "Couldn't load the eval report",
    );
    expect(screen.getByRole("alert")).toHaveTextContent("API unreachable");
    expect(screen.getByRole("alert")).toHaveTextContent("Reference: req-7");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(
      await screen.findByRole("table", { name: "Scenarios" }),
    ).toBeVisible();
  });
});
