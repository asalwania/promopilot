import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EvalScenarioTable } from "@/components/eval-scenario-table";

import { recordedReport, scenario } from "./fixtures/evals";

const table = () => screen.getByRole("table", { name: "Scenarios" });
const scenarioNames = () =>
  within(table())
    .getAllByRole("rowheader")
    .map((cell) => cell.textContent);
const row = (name: string) =>
  within(table()).getByRole("rowheader", { name }).closest("tr")!;

describe("EvalScenarioTable", () => {
  it("has a row per scenario, in report order, with its result", () => {
    render(<EvalScenarioTable scenarios={recordedReport.scenarios} />);

    expect(scenarioNames()).toEqual([
      "amend-budget-cut-christmas-2025",
      "cannibal-bakery-diwali-2026",
      "cannibal-personal-care-offseason",
      "clear-curd-diwali-2025",
      "demo-budget-cut-drop-west",
      "diwali-no-budget",
      "infeasible-clearance-high-margin",
      "price-war-staples-christmas-2025",
    ]);
    const curd = within(row("clear-curd-diwali-2025"));
    expect(curd.getByText("Fail")).toBeVisible();
    expect(curd.getByText("Overstock clearance")).toBeVisible();
    expect(curd.getByText("W50")).toBeVisible();
    expect(curd.getByText("failed")).toBeVisible();
    expect(curd.getByText("3/4")).toBeVisible();
    expect(curd.getByText("100%")).toBeVisible();

    const amend = within(row("amend-budget-cut-christmas-2025"));
    expect(amend.getByText("Pass")).toBeVisible();
    expect(amend.getByText("beats")).toBeVisible();
    expect(amend.getByText("23.7%")).toBeVisible();
    expect(amend.getByText("₹5.10")).toBeVisible();
  });

  it("shows a warning when a run replayed with a cassette miss", () => {
    render(<EvalScenarioTable scenarios={recordedReport.scenarios} />);

    expect(
      within(row("diwali-no-budget")).getByText("1 cassette miss"),
    ).toBeVisible();
  });

  it("filters to the failed scenarios and to one group", async () => {
    render(<EvalScenarioTable scenarios={recordedReport.scenarios} />);

    fireEvent.click(screen.getByRole("checkbox", { name: "Failed only" }));
    expect(scenarioNames()).toEqual([
      "cannibal-bakery-diwali-2026",
      "cannibal-personal-care-offseason",
      "clear-curd-diwali-2025",
      "demo-budget-cut-drop-west",
    ]);

    fireEvent.change(screen.getByRole("combobox", { name: "Group" }), {
      target: { value: "mid_plan_amendments" },
    });
    expect(scenarioNames()).toEqual(["demo-budget-cut-drop-west"]);

    fireEvent.click(screen.getByRole("checkbox", { name: "Failed only" }));
    expect(scenarioNames()).toEqual([
      "amend-budget-cut-christmas-2025",
      "demo-budget-cut-drop-west",
    ]);
  });

  it("says so when no scenario matches the filters", async () => {
    render(<EvalScenarioTable scenarios={[scenario("diwali-no-budget")]} />);

    fireEvent.click(screen.getByRole("checkbox", { name: "Failed only" }));

    expect(
      screen.getByText("No scenario matches these filters."),
    ).toBeVisible();
  });

  it("opens a run's trace as the report holds it, with a link to the scenario", async () => {
    render(<EvalScenarioTable scenarios={recordedReport.scenarios} />);

    const toggle = screen.getByRole("button", {
      name: "Details for diwali-no-budget",
    });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    const details = screen.getByRole("region", {
      name: "diwali-no-budget run 1",
    });
    expect(within(details).getByText("Passed")).toBeVisible();
    const route = within(details).getByRole("list", { name: "Route" });
    expect(within(route).getAllByRole("listitem")[0]).toHaveTextContent(
      "context",
    );
    expect(within(details).getByText("marketing_budget")).toBeVisible();
    expect(within(details).getByText("3f9c2a7e1b4d")).toBeVisible();
    expect(
      within(details).getByText("declares_infeasible: false", { exact: false }),
    ).toBeVisible();
    expect(
      screen.getByRole("link", { name: "Scenario YAML: diwali-no-budget" }),
    ).toHaveAttribute(
      "href",
      "https://github.com/asalwania/promopilot/blob/main/backend/evals/scenarios/diwali-no-budget.yaml",
    );
  });

  it("names every failed property and violation in a failed run's detail", async () => {
    render(<EvalScenarioTable scenarios={recordedReport.scenarios} />);

    fireEvent.click(
      screen.getByRole("button", {
        name: "Details for clear-curd-diwali-2025",
      }),
    );

    const details = screen.getByRole("region", {
      name: "clear-curd-diwali-2025 run 1",
    });
    expect(within(details).getByText("Failed")).toBeVisible();
    const violations = within(details).getByRole("list", {
      name: "Violations",
    });
    expect(within(violations).getAllByRole("listitem")).not.toHaveLength(0);
  });
});
