import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { NotSelectedList } from "@/components/not-selected-list";
import type { PlanRevision } from "@/lib/api/sessions";

import { notSelected } from "./fixtures/checks";

type NotSelectedReason =
  PlanRevision["not_selected"][number]["reasons"][number];

function rows(): HTMLElement[] {
  const table = screen.getByRole("table", { name: "Not selected options" });
  return within(table).getAllByRole("row").slice(1);
}

describe("NotSelectedList", () => {
  it("lists the best options left out, best first, with why each was left out", () => {
    render(<NotSelectedList options={notSelected} />);

    const panel = screen.getByRole("region", { name: "Not selected" });
    expect(panel).toHaveTextContent("The best options the optimiser left out");
    const [bundle, bogo] = rows();
    expect(
      within(bundle).getByRole("rowheader", { name: "SKU0021" }),
    ).toBeInTheDocument();
    expect(
      within(bundle)
        .getAllByRole("cell")
        .slice(0, 6)
        .map((cell) => cell.textContent),
    ).toEqual(["West", "Bundle + SKU0042", "15%", "W105", "2 wk", "Families"]);
    expect(bundle).toHaveTextContent("Over the marketing budget");
    expect(bundle).toHaveTextContent("Cannibalises SKU0003, SKU0011");
    expect(within(bundle).getByText("₹14,250")).toHaveAttribute(
      "title",
      expect.stringContaining("Source: run_optimizer"),
    );

    expect(within(bogo).getAllByRole("cell")[1]).toHaveTextContent(
      "Buy one get one",
    );
    expect(bogo).toHaveTextContent("Low uplift: not worth it on its own");
    expect(within(bogo).getByText("-₹250")).toBeInTheDocument();
  });

  it("names every reason the optimiser gives", () => {
    const reasons: Record<NotSelectedReason, string> = {
      low_uplift: "Low uplift: not worth it on its own",
      out_of_stock: "Not enough stock for its P90 units",
      breaks_policy:
        "Breaks company policy: promo window, maximum discount or unit cost",
      over_budget: "Over the marketing budget",
      over_regional_budget: "Over the regional budget cap",
      breaks_margin: "Breaks the minimum margin",
      max_promoted_skus: "Too many promoted SKUs in its category and region",
      misses_clearance_target: "Would leave a clearance target unmet",
      breaks_kvi_tolerance: "Breaks the KVI price tolerance",
      strong_substitute:
        "Strong substitute of SKU0003, which the plan promotes at the same time",
      cannibalises: "Cannibalises SKU0003",
      time_limit: "Not settled before the solver's time limit",
    };
    render(
      <NotSelectedList
        options={[
          {
            ...notSelected[0],
            reasons: Object.keys(reasons) as NotSelectedReason[],
            cannibalises: ["SKU0003"],
          },
        ]}
      />,
    );

    const list = within(rows()[0]).getByRole("list", { name: "Reasons" });
    expect(
      within(list)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual(Object.values(reasons));
  });

  it("says so when no option was left out", () => {
    render(<NotSelectedList options={[]} />);

    expect(
      screen.getByRole("region", { name: "Not selected" }),
    ).toHaveTextContent("No worthwhile option was left out.");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
