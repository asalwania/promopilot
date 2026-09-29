import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EvalMetricCards } from "@/components/eval-metric-cards";

import { metric, recordedReport } from "./fixtures/evals";

const card = (label: string) => screen.getByRole("article", { name: label });

describe("EvalMetricCards", () => {
  it("shows each metric against its target with the report's pass or fail", () => {
    render(<EvalMetricCards metrics={recordedReport.metrics} />);

    const constraints = card("Constraint satisfaction");
    expect(within(constraints).getByText("96.6%")).toBeVisible();
    expect(within(constraints).getByText("Target ≥ 100%")).toBeVisible();
    expect(within(constraints).getByText("28 of 29")).toBeVisible();
    expect(within(constraints).getByText("Fail")).toBeVisible();

    const extraction = card("Extraction accuracy");
    expect(within(extraction).getByText("100%")).toBeVisible();
    expect(within(extraction).getByText("Target ≥ 95%")).toBeVisible();
    expect(within(extraction).getByText("Pass")).toBeVisible();

    const regret = card("Regret (median, against the best plan)");
    expect(within(regret).getByText("23.5%")).toBeVisible();
    expect(within(regret).getByText("Target ≤ 10%")).toBeVisible();
    expect(within(regret).getByText("Fail")).toBeVisible();
  });

  it("counts the targets met as the report judged them", () => {
    render(<EvalMetricCards metrics={recordedReport.metrics} />);

    expect(screen.getByText("10 of 12 targets met")).toBeVisible();
  });

  it("shows a reported metric's aim without judging it", () => {
    render(<EvalMetricCards metrics={recordedReport.metrics} />);

    const wape = card("Baseline WAPE, store x SKU x segment");
    expect(within(wape).getByText("43.5%")).toBeVisible();
    expect(within(wape).getByText("Report · aim ≤ 25%")).toBeVisible();
    expect(within(wape).getByText("Reported")).toBeVisible();
    expect(within(wape).queryByText(/Pass|Fail/)).toBeNull();

    const breaches = card("Oracle breach rate");
    expect(within(breaches).getByText("Report")).toBeVisible();
    expect(
      within(breaches).getByText("promo cost over budget 7"),
    ).toBeVisible();
  });

  it("shows a metric with nothing scored as n/a", () => {
    render(<EvalMetricCards metrics={recordedReport.metrics} />);

    const consistency = card(
      "Consistency (Jaccard of selected SKUs across runs)",
    );
    expect(within(consistency).getByText("n/a")).toBeVisible();
    expect(within(consistency).getByText("Target ≥ 90%")).toBeVisible();
    expect(within(consistency).getByText("Not scored")).toBeVisible();
  });

  it("shows time and cost in their units", () => {
    render(<EvalMetricCards metrics={recordedReport.metrics} />);

    expect(
      within(card("P50 session time")).getByText("2 min 29 s"),
    ).toBeVisible();
    expect(within(card("P50 session cost")).getByText("₹3.04")).toBeVisible();
  });

  it("names the eval metric each value comes from", () => {
    render(<EvalMetricCards metrics={recordedReport.metrics} />);

    expect(
      within(card("Constraint satisfaction")).getByText("96.6%"),
    ).toHaveAttribute(
      "title",
      "Source: make eval · constraint_satisfaction · 28 of 29",
    );
  });

  it("groups the cards, and puts a metric it does not know under Other", () => {
    const novel = { ...metric("grounding"), name: "novelty", label: "Novelty" };
    render(<EvalMetricCards metrics={[...recordedReport.metrics, novel]} />);

    const groups = screen
      .getAllByRole("region")
      .map((region) => region.getAttribute("aria-label"));
    expect(groups).toEqual([
      "Constraints",
      "Agent behaviour",
      "Plan quality",
      "Model recovery",
      "Latency and cost",
      "Other",
    ]);
    const behaviour = screen.getByRole("region", { name: "Agent behaviour" });
    expect(
      within(behaviour)
        .getAllByRole("article")
        .map((article) => article.getAttribute("aria-label")),
    ).toEqual([
      "Extraction accuracy",
      "Clarification behaviour",
      "Infeasibility handling",
      "Grounding",
    ]);
    expect(
      within(screen.getByRole("region", { name: "Other" })).getByRole(
        "article",
        { name: "Novelty" },
      ),
    ).toBeVisible();
  });
});
