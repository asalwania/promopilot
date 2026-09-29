import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CompetitorPanel } from "@/components/competitor-panel";
import type { CompetitorGap } from "@/lib/api/catalog";
import type { PlanningRequest, PlanRevision } from "@/lib/api/sessions";

import { awaitingApprovalSession, undercutGaps } from "./fixtures/sessions";

const baseRevision = awaitingApprovalSession.plan_revision as PlanRevision;
const RESPONSE = [
  "Competitor is 12.0% cheaper on SKU0003 (Masala Chips 150g) in North (₹88.00 vs ₹100.00).",
  "Matching on 1 SKU: the plan prices it at or below the competitor.",
];
const revision: PlanRevision = {
  ...baseRevision,
  explanation: {
    ...baseRevision.explanation!,
    competitor_response: RESPONSE,
  },
};
const request: PlanningRequest = {
  ...awaitingApprovalSession.planning_request!,
  scope: {
    regions: ["North", "West"],
    categories: ["Snacks", "Beverages"],
    sku_ids: [],
  },
};

const gap = (overrides: Partial<CompetitorGap>): CompetitorGap => ({
  ...undercutGaps[0],
  ...overrides,
});
// The gaps the API returns for every KVI; the panel keeps the request's scope.
const gaps: CompetitorGap[] = [
  undercutGaps[1],
  undercutGaps[0],
  gap({ sku_id: "SKU0009", name: "Salted Peanuts 200g", undercut: false }),
  gap({ region: "East", sku_id: "SKU0021" }),
  gap({ sku_id: "SKU0050", category: "Dairy", name: "Milk 1L" }),
];

function renderPanel(
  props: Partial<Parameters<typeof CompetitorPanel>[0]> = {},
) {
  return render(
    <CompetitorPanel
      prices={{ status: "ready", gaps }}
      request={request}
      revision={revision}
      {...props}
    />,
  );
}

function rows() {
  const table = screen.getByRole("table", { name: "Competitor gaps" });
  return within(table).getAllByRole("row").slice(1);
}

describe("CompetitorPanel", () => {
  it("lists the KVI gaps in the request's scope, undercuts first", () => {
    renderPanel();

    expect(
      rows().map((row) => within(row).getAllByRole("cell")[0].textContent),
    ).toEqual([
      "SKU0003Masala Chips 150g",
      "SKU0011Cola 750ml",
      "SKU0009Salted Peanuts 200g",
    ]);
  });

  it("shows each gap's prices and flags the undercuts", () => {
    renderPanel();

    const [chips, cola] = rows();
    expect(
      within(chips)
        .getAllByRole("cell")
        .slice(1, 6)
        .map((cell) => cell.textContent),
    ).toEqual(["North", "₹100.00", "₹88.00", "12%", "0.88"]);
    expect(within(chips).getByText("Undercut")).toBeInTheDocument();
    expect(within(cola).queryByText("Undercut")).not.toBeInTheDocument();
    expect(within(chips).getByText("12%")).toHaveAttribute(
      "title",
      "Source: get_competitor_gaps · competitor price in W103",
    );
  });

  it("names the plan line that promotes each KVI, if any", () => {
    renderPanel();

    const planLine = (row: HTMLElement) =>
      within(row).getAllByRole("cell").at(-1)?.textContent;
    const [chips, cola, peanuts] = rows();
    expect(planLine(chips)).toBe("% off 20%");
    expect(planLine(cola)).toBe("% off 20%");
    expect(planLine(peanuts)).toBe("Not promoted");
  });

  it("gives the planner's response to the undercuts", () => {
    renderPanel();

    const response = screen.getByRole("region", {
      name: "Planner's response",
    });
    expect(
      within(response)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual(RESPONSE);
  });

  it("points to the plan summary when the revision kept no response", () => {
    renderPanel({ revision: baseRevision });

    expect(
      screen.getByText("The plan summary gives the planner's response."),
    ).toBeInTheDocument();
  });

  it("says when no KVI in scope is undercut", () => {
    renderPanel({
      prices: { status: "ready", gaps: [undercutGaps[1]] },
      revision: baseRevision,
    });

    expect(
      screen.getByText(
        "No KVI in scope is undercut, so the plan answers none.",
      ),
    ).toBeInTheDocument();
  });

  it("says when no KVI in scope has a competitor price", () => {
    renderPanel({ prices: { status: "ready", gaps: [gaps[3]] } });

    expect(
      screen.getByText("No KVI in scope has a competitor price."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("shows while the prices load", () => {
    renderPanel({ prices: { status: "loading" } });

    expect(screen.getByText("Loading competitor prices…")).toBeInTheDocument();
  });

  it("says why the prices failed and retries them", () => {
    const retry = vi.fn();
    renderPanel({ prices: { status: "error", reason: "HTTP 503", retry } });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Couldn't load competitor prices: HTTP 503",
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(retry).toHaveBeenCalledOnce();
  });
});
