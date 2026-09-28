import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MechanismDrawer } from "@/components/mechanism-drawer";

import { planLines } from "./fixtures/sessions";

function openDrawer() {
  render(<MechanismDrawer planned={planLines[0]} />);
  fireEvent.click(
    screen.getByRole("button", {
      name: "Compare mechanisms for SKU0003 in North",
    }),
  );
  return screen.getByRole("dialog", {
    name: "Mechanisms for SKU0003 in North",
  });
}

function cellsOf(row: HTMLElement) {
  return within(row)
    .getAllByRole("cell")
    .map((cell) => cell.textContent);
}

// Opening the first dialog of a run is slow under a busy parallel suite.
describe("MechanismDrawer", { timeout: 15_000 }, () => {
  it("compares each mechanism's best option with the chosen one", () => {
    const drawer = openDrawer();

    const table = within(drawer).getByRole("table", {
      name: "Mechanism comparison",
    });
    const [, ...rows] = within(table).getAllByRole("row");
    expect(rows.map(cellsOf)).toEqual([
      [
        "% offChosen",
        "20% · 4 wk from W105 · All customers",
        "813",
        "25%",
        "₹13,813",
        "-₹13,813",
        "₹6,188",
      ],
      [
        "Bundle",
        "15% · 2 wk from W105 · Families",
        "300",
        "23.5%",
        "₹6,250",
        "-₹2,100",
        "₹5,320",
      ],
      ["Buy one get one", "No option: below cost", "", "", "", "", ""],
    ]);
    expect(within(table).getByText("₹5,320")).toHaveAttribute(
      "title",
      "Source: compare_mechanisms · ₹5,320",
    );
  });

  it("shows a bundle suggestion with the pair, basket lift and incremental profit", () => {
    const drawer = openDrawer();

    const bundle = within(drawer).getByRole("region", {
      name: "Bundle suggestion",
    });
    expect(bundle).toHaveTextContent(
      "Bundle SKU0003 with SKU0042: basket lift 2.4×, expected incremental profit -₹2,100",
    );
    expect(within(bundle).getByText("2.4×")).toHaveAttribute(
      "title",
      "Source: compare_mechanisms · how much more often the pair is bought together than by chance",
    );
  });

  it("offers no comparison for a line that kept none", () => {
    render(<MechanismDrawer planned={planLines[1]} />);

    expect(
      screen.queryByRole("button", { name: /Compare mechanisms/ }),
    ).not.toBeInTheDocument();
  });
});
