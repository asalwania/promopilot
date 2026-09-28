import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TraceTimeline } from "@/components/trace-timeline";
import type { TraceConnection } from "@/lib/trace-stream";

import { traceEvents } from "./fixtures/trace";

function renderTimeline(
  connection: TraceConnection = "live",
  events = traceEvents,
  onRetry = () => {},
) {
  return render(
    <TraceTimeline events={events} connection={connection} onRetry={onRetry} />,
  );
}

function runs() {
  return within(screen.getByRole("list", { name: "Trace timeline" }))
    .getAllByRole("listitem")
    .filter((item) => item.dataset.run !== undefined);
}

describe("TraceTimeline", () => {
  it("groups the events into one entry per node run, in order", () => {
    renderTimeline();

    expect(
      runs().map((run) => within(run).getByRole("heading").textContent),
    ).toEqual([
      "Context agentDone1.3 s",
      "PlannerDone42.0 s",
      "CriticDone300 ms",
      "Planner · attempt 2Failed900 ms",
      "ApprovalPaused5 ms",
      "ExplainerRunning",
    ]);
  });

  it("shows a failed node's error", () => {
    renderTimeline();

    expect(within(runs()[3]).getByRole("alert")).toHaveTextContent(
      "Optimiser crashed",
    );
  });

  it("shows tool calls with their outcome, arguments and result", () => {
    renderTimeline();
    const planner = runs()[1];

    const ok = within(planner).getByText("get_inventory_status").closest("li");
    expect(ok).toHaveTextContent("ok");
    expect(ok).toHaveTextContent('"regions": [');
    expect(ok).toHaveTextContent('"items": "<12 items>"');

    const failed = within(planner).getByText("run_optimizer").closest("li");
    expect(failed).toHaveTextContent("error: unknown_candidate_set");
    expect(failed).toHaveTextContent('"No candidate set abc"');
  });

  it("shows decisions, findings and clarification questions", () => {
    renderTimeline();

    const critic = runs()[2];
    expect(critic).toHaveTextContent(
      "open_issuesThe plan has 1 open issue; the planner tries again.",
    );
    expect(critic).toHaveTextContent(
      "plan_validationBUDGETPromo cost ₹2,10,000 is over the ₹2,00,000 budget.",
    );
    expect(runs()[0]).toHaveTextContent(
      "Asked for clarificationWhat is the marketing budget?",
    );
  });

  it("shows each LLM call's model, tokens and cost", () => {
    renderTimeline();

    expect(runs()[0]).toHaveTextContent(
      "gpt-4.1-mini · 12,345 in / 678 out · ₹0.58",
    );
    expect(runs()[1]).toHaveTextContent(
      "local-model · 2,000 in / 100 out · no price",
    );
  });

  it("puts each event's clock time on hover", () => {
    renderTimeline();

    expect(
      within(runs()[1]).getByText("run_optimizer").closest("[title]"),
    ).toHaveAttribute(
      "title",
      new Intl.DateTimeFormat("en-IN", { timeStyle: "medium" }).format(
        new Date(traceEvents[6].at),
      ),
    );
  });

  it.each([
    ["connecting", "Connecting…", "Connecting to the trace…"],
    ["live", "Live", "Waiting for the agent's first step…"],
    ["ended", "Final", "No trace was recorded for this session."],
  ] as const)(
    "while %s with no events, says so",
    (connection, indicator, empty) => {
      renderTimeline(connection, []);

      const timeline = screen.getByRole("region", { name: "Agent trace" });
      expect(timeline).toHaveTextContent(indicator);
      expect(timeline).toHaveTextContent(empty);
      expect(
        screen.queryByRole("list", { name: "Trace timeline" }),
      ).not.toBeInTheDocument();
    },
  );

  it("keeps the events shown while it reconnects", () => {
    renderTimeline("reconnecting");

    const timeline = screen.getByRole("region", { name: "Agent trace" });
    expect(timeline).toHaveTextContent("Reconnecting…");
    expect(timeline).toHaveTextContent(
      "The trace continues where it left off.",
    );
    expect(runs()).toHaveLength(6);
  });

  it("reports a lost stream with a Retry button", () => {
    const onRetry = vi.fn();
    renderTimeline("error", traceEvents, onRetry);

    const timeline = screen.getByRole("region", { name: "Agent trace" });
    expect(within(timeline).getAllByRole("alert")[0]).toHaveTextContent(
      "Lost the trace stream.",
    );
    expect(runs()).toHaveLength(6);

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});
