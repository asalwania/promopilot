import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PlanTable, type PlanRow } from "@/components/plan-table";

import {
  awaitingApprovalSession,
  legacyPlanLine,
  planLines,
  undercutGaps,
} from "./fixtures/sessions";

const simulation = awaitingApprovalSession.plan_revision!.simulation!;
const RUNS = { n_runs: simulation.n_runs, seed: simulation.seed };

const northRow: PlanRow = {
  planned: planLines[0],
  simulated: simulation.lines[0],
  rationale:
    "SKU0003 in North at 20% off is the best option for its SKU and region.",
  undercut: undercutGaps[0],
};

function cellsOf(row: HTMLElement) {
  return within(row)
    .getAllByRole("cell")
    .map((cell) => cell.textContent);
}

function renderTable(rows: PlanRow[]) {
  render(<PlanTable region="North" rows={rows} runs={RUNS} />);
  return screen.getByRole("table", { name: "Plan lines in North" });
}

describe("PlanTable", () => {
  it("shows each line's decision, uplift, profit range, risk and cost", () => {
    const table = renderTable([northRow]);

    const headers = within(table)
      .getAllByRole("columnheader")
      .map((header) => header.textContent);
    expect(headers).toEqual([
      "SKU",
      "Mechanism",
      "Depth",
      "Start",
      "Duration",
      "Target segment",
      "Uplift",
      "Profit P10–P90",
      "Stock-out risk",
      "Promo cost",
      "Expected incremental profit",
      "Notes",
      "Details",
    ]);
    const [, row] = within(table).getAllByRole("row");
    expect(cellsOf(row).slice(0, 12)).toEqual([
      "SKU0003",
      "% off",
      "20%",
      "W105",
      "4 wk",
      "All customers",
      "+62.5%",
      "₹11,200 – ₹13,280",
      "31%",
      "₹13,813",
      "-₹13,813",
      "CannibalisationHaloUndercut",
    ]);
  });

  it("names the tool behind every number in a tooltip", () => {
    const table = renderTable([northRow]);

    expect(within(table).getByText("+62.5%")).toHaveAttribute(
      "title",
      "Source: generate_candidates · 813 units against a baseline of 500 over the promo weeks",
    );
    expect(within(table).getByText("₹11,200")).toHaveAttribute(
      "title",
      "Source: simulate_plan · gross profit over the promo weeks: P10 ₹11,200, P50 ₹12,960, P90 ₹13,280 · 1000 runs, seed 0",
    );
    expect(within(table).getByText("31%")).toHaveAttribute(
      "title",
      "Source: simulate_plan · share of 1000 runs that ran out of stock",
    );
    expect(within(table).getByText("₹13,813")).toHaveAttribute(
      "title",
      "Source: generate_candidates · ₹13,813",
    );
    expect(within(table).getByText("20%")).toHaveAttribute(
      "title",
      "Source: run_optimizer",
    );
  });

  it("uses lakh and crore as the rationales do, with exact rupees in the tooltip", () => {
    const table = renderTable([
      { planned: planLines[1], simulated: simulation.lines[1] },
    ]);

    expect(within(table).getByText("₹1.23 lakh")).toHaveAttribute(
      "title",
      "Source: generate_candidates · ₹1,23,456",
    );
  });

  it("shows a dash where a line has no uplift or simulation", () => {
    const table = renderTable([{ planned: legacyPlanLine }]);

    const [, row] = within(table).getAllByRole("row");
    const cells = cellsOf(row);
    expect(cells[6]).toBe("—");
    expect(cells[7]).toBe("—");
    expect(cells[8]).toBe("—");
  });

  it("opens a line's rationale, uplift by segment and callouts", () => {
    renderTable([northRow]);

    const toggle = screen.getByRole("button", {
      name: "Details for SKU0003 in North",
    });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(northRow.rationale!)).not.toBeInTheDocument();

    fireEvent.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(northRow.rationale!)).toBeInTheDocument();
    expect(
      screen.getByRole("table", {
        name: "Uplift by segment for SKU0003 in North",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "Cannibalisation" }),
    ).toHaveTextContent("Promoting SKU0003 reduces SKU0004's units by 13%");
    expect(screen.getByRole("region", { name: "Halo" })).toHaveTextContent(
      "Promoting SKU0003 lifts SKU0020's units by 8%",
    );
    expect(
      screen.getByRole("note", { name: "Competitor undercuts" }),
    ).toHaveTextContent("Competitor is 12.0% cheaper on Masala Chips 150g");
  });

  it("shows each segment's units, baseline and uplift from the demand model", () => {
    renderTable([northRow]);
    fireEvent.click(
      screen.getByRole("button", { name: "Details for SKU0003 in North" }),
    );

    const segments = screen.getByRole("table", {
      name: "Uplift by segment for SKU0003 in North",
    });
    const [, ...rows] = within(segments).getAllByRole("row");
    expect(rows.map(cellsOf)).toEqual([
      ["Value Seekers", "300", "150", "+100%"],
      ["Families", "263", "175", "+50%"],
      ["Premium", "100", "80", "+25%"],
      ["Young Urban", "150", "95", "+57.9%"],
    ]);
    expect(within(segments).getByText("+50%")).toHaveAttribute(
      "title",
      "Source: estimate_demand",
    );
  });

  it("says when a line kept no segment breakdown", () => {
    renderTable([{ planned: legacyPlanLine }]);
    fireEvent.click(
      screen.getByRole("button", { name: "Details for SKU0011 in West" }),
    );

    expect(
      screen.getByText("No segment breakdown was kept for this line."),
    ).toBeInTheDocument();
  });
});
