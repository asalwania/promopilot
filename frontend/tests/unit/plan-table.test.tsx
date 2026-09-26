import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PlanTable } from "@/components/plan-table";

import { planLines } from "./fixtures/sessions";

function cellsOf(row: HTMLElement) {
  return within(row)
    .getAllByRole("cell")
    .map((cell) => cell.textContent);
}

describe("PlanTable", () => {
  it("renders one row per plan line with the columns the manager reads", () => {
    render(<PlanTable lines={planLines} />);

    const table = screen.getByRole("table", { name: "Plan lines" });
    const headers = within(table)
      .getAllByRole("columnheader")
      .map((header) => header.textContent);
    expect(headers).toEqual([
      "SKU",
      "Region",
      "Mechanism",
      "Depth",
      "Start",
      "Duration",
      "Target segment",
      "Promo cost",
      "Expected incremental profit",
    ]);

    const [, ...rows] = within(table).getAllByRole("row");
    expect(rows.map(cellsOf)).toEqual([
      [
        "SKU0003",
        "North",
        "% off",
        "20%",
        "W105",
        "4 wk",
        "All customers",
        "₹13,813",
        "-₹13,813",
      ],
      [
        "SKU0011",
        "West",
        "% off",
        "20%",
        "W105",
        "4 wk",
        "All customers",
        "₹1,23,456",
        "-₹1,23,456",
      ],
    ]);
  });
});
