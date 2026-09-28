import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RegionPlanTabs } from "@/components/region-plan-tabs";

import { awaitingApprovalSession, undercutGaps } from "./fixtures/sessions";

const revision = awaitingApprovalSession.plan_revision!;

function renderTabs(regions = ["North", "West"] as const) {
  render(
    <RegionPlanTabs
      revision={revision}
      regions={[...regions]}
      competitorGaps={undercutGaps}
    />,
  );
}

function skusIn(table: HTMLElement) {
  const [, ...rows] = within(table).getAllByRole("row");
  return rows.map((row) => within(row).getAllByRole("cell")[0].textContent);
}

describe("RegionPlanTabs", () => {
  it("has a tab per region in the request, then one to compare them", () => {
    renderTabs();

    const tabs = within(screen.getByRole("tablist", { name: "Plan regions" }))
      .getAllByRole("tab")
      .map((tab) => tab.textContent);
    expect(tabs).toEqual(["North (1)", "West (2)", "Compare regions"]);
    expect(screen.getByRole("tab", { name: "North (1)" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("shows the selected region's plan lines, with its rationales", () => {
    renderTabs();

    expect(
      skusIn(screen.getByRole("table", { name: "Plan lines in North" })),
    ).toEqual(["SKU0003"]);

    fireEvent.click(screen.getByRole("tab", { name: "West (2)" }));

    const west = screen.getByRole("table", { name: "Plan lines in West" });
    expect(skusIn(west)).toEqual(["SKU0011", "SKU0003"]);
    fireEvent.click(
      within(west).getByRole("button", { name: "Details for SKU0003 in West" }),
    );
    expect(
      screen.getByText("SKU0003 in West sells best to Families as a BOGO."),
    ).toBeInTheDocument();
  });

  it("shows the region's stock-out risk from the simulation", () => {
    renderTabs();

    expect(screen.getByText("31%", { selector: "p *" })).toHaveAttribute(
      "title",
      "Source: simulate_plan · share of 1000 runs in which a North plan line ran out",
    );
  });

  it("says so for a region in the request with no plan line", () => {
    renderTabs(["North", "East", "West"] as never);

    fireEvent.click(screen.getByRole("tab", { name: "East (0)" }));

    expect(screen.getByText("No plan line in East.")).toBeInTheDocument();
  });

  it("opens on the first region that has a plan line", () => {
    render(
      <RegionPlanTabs
        revision={{
          ...revision,
          lines: revision.lines.filter((line) => line.line.region === "West"),
          explanation: null,
        }}
        regions={["East", "West"]}
      />,
    );

    expect(screen.getByRole("tab", { name: "East (0)" })).toHaveAttribute(
      "aria-selected",
      "false",
    );
    expect(screen.getByRole("tab", { name: "West (2)" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("compares the same SKU side by side across regions", () => {
    renderTabs();

    fireEvent.click(screen.getByRole("tab", { name: "Compare regions" }));

    const table = screen.getByRole("table", { name: "Regions side by side" });
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((header) => header.textContent),
    ).toEqual(["SKU", "North", "West"]);
    const [, ...rows] = within(table).getAllByRole("row");
    expect(
      rows.map((row) =>
        within(row)
          .getAllByRole("cell")
          .map((cell) => cell.textContent),
      ),
    ).toEqual([
      [
        "SKU0003",
        "% off 20% · 4 wk · All customers-₹13,813",
        "Buy one get one 50% · 2 wk · Families₹4,250",
      ],
      ["SKU0011", "—", "% off 20% · 4 wk · All customers-₹1.23 lakh"],
    ]);
  });
});
