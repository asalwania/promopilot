import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RegretChart } from "@/components/regret-chart";

import { metric, recordedReport } from "./fixtures/evals";

function renderChart() {
  return render(
    <RegretChart
      scenarios={recordedReport.scenarios}
      regret={metric("regret")}
    />,
  );
}

describe("RegretChart", () => {
  it("renders with the report's median and the target marked", () => {
    renderChart();

    const figure = screen.getByRole("figure", {
      name: "Regret against the best plan, per scored run",
    });
    const legend = within(figure).getByRole("list", { name: "Legend" });
    expect(within(legend).getByText("Median 23.5%")).toBeVisible();
    expect(within(legend).getByText("Target ≤ 10%")).toBeVisible();
  });

  it("lists each run's regret from lowest to highest, marking what the axis clips", async () => {
    renderChart();

    fireEvent.click(screen.getByRole("button", { name: "Show values" }));

    const rows = within(screen.getByRole("table", { name: "Regret per run" }))
      .getAllByRole("row")
      .slice(1)
      .map((row) =>
        within(row)
          .getAllByRole("cell")
          .map((cell) => cell.textContent),
      );
    expect(rows).toEqual([
      ["cannibal-personal-care-offseason", "-1075.6%", "Beyond the axis"],
      ["diwali-no-budget", "9.3%", ""],
      ["amend-budget-cut-christmas-2025", "23.7%", ""],
      ["cannibal-bakery-diwali-2026", "70.7%", ""],
      ["clear-curd-diwali-2025", "100%", ""],
      ["price-war-staples-christmas-2025", "240.6%", "Beyond the axis"],
    ]);
  });

  it("says how many runs have no regret", () => {
    renderChart();

    expect(
      screen.getByText(
        "2 runs have no regret: no scored plan, or the best plan is infeasible.",
      ),
    ).toBeVisible();
  });

  it("says so when no run has a regret", () => {
    render(<RegretChart scenarios={[]} regret={metric("regret")} />);

    expect(screen.getByText("No run has a regret to show.")).toBeVisible();
    expect(screen.queryByRole("figure")).toBeNull();
  });
});
