import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AssumptionsPanel } from "@/components/assumptions-panel";

import { contextAssumptions, fallbackAssumptions } from "./fixtures/sessions";

function rowOf(field: string): HTMLElement {
  const table = screen.getByRole("table", { name: "Assumptions" });
  const cell = within(table).getByRole("rowheader", { name: field });
  return cell.closest("tr")!;
}

describe("AssumptionsPanel", () => {
  it("lists every assumption with its value, source and confidence", () => {
    render(
      <AssumptionsPanel assumptions={contextAssumptions} status="planning" />,
    );

    const panel = screen.getByRole("region", { name: "Assumptions" });
    const rows = within(panel).getAllByRole("row").slice(1);
    expect(
      rows.map((row) => within(row).getAllByRole("cell")[0].textContent),
    ).toEqual([
      "North, West",
      "Snacks",
      "₹200,000",
      expect.stringContaining(
        "15.0% (company policy; the brief asked for 5.0%)",
      ),
      "5.0% (company policy)",
      "SKU0003 in North",
    ]);

    const regions = rowOf("Regions");
    expect(regions).toHaveTextContent("From brief");
    expect(within(regions).getByText("100%")).toHaveAttribute(
      "title",
      expect.stringContaining("Source: Context agent"),
    );
    expect(rowOf("KVI price tolerance")).toHaveTextContent("Default");
    expect(rowOf("Overstocked SKUs")).toHaveTextContent("From data");
  });

  it("highlights a low-confidence reading", () => {
    render(
      <AssumptionsPanel assumptions={contextAssumptions} status="planning" />,
    );

    const categories = rowOf("Categories");
    expect(categories).toHaveTextContent("83%");
    expect(categories).toHaveTextContent("Low confidence");
    expect(rowOf("Regions")).not.toHaveTextContent("Low confidence");
  });

  it("highlights a value company policy clamped, with the reason", () => {
    render(
      <AssumptionsPanel assumptions={contextAssumptions} status="planning" />,
    );

    const margin = rowOf("Minimum margin");
    expect(margin).toHaveTextContent("Flagged");
    expect(margin).toHaveTextContent(
      "The brief's minimum margin of 5.0% is below the company-policy floor of 15.0%; the floor applies.",
    );
    expect(rowOf("Marketing budget")).not.toHaveTextContent("Flagged");
  });

  it("says how many assumptions need a look", () => {
    render(
      <AssumptionsPanel assumptions={contextAssumptions} status="planning" />,
    );

    expect(
      screen.getByRole("region", { name: "Assumptions" }),
    ).toHaveTextContent("2 need a look");
  });

  it("marks a reading made by rules while the language model was down", () => {
    render(
      <AssumptionsPanel assumptions={fallbackAssumptions} status="planning" />,
    );

    expect(screen.getByRole("note")).toHaveTextContent(
      "The language model was unavailable: these were read by rules.",
    );
    const regions = rowOf("Regions");
    expect(regions).toHaveTextContent("Read by rules");
    expect(regions).toHaveTextContent("Low confidence");
    expect(rowOf("As-of week")).toHaveTextContent("Read by rules");
  });

  it("shows no fallback note for a language-model reading", () => {
    render(
      <AssumptionsPanel assumptions={contextAssumptions} status="planning" />,
    );

    expect(screen.queryByRole("note")).not.toBeInTheDocument();
    expect(screen.queryByText("Read by rules")).not.toBeInTheDocument();
  });

  it("shows an unknown field by its name", () => {
    render(
      <AssumptionsPanel
        assumptions={[{ ...contextAssumptions[0], field: "new_field" }]}
        status="planning"
      />,
    );

    expect(rowOf("new_field")).toHaveTextContent("North, West");
  });

  it("says the brief is still being read while planning starts", () => {
    render(<AssumptionsPanel assumptions={[]} status="planning" />);

    expect(
      screen.getByRole("region", { name: "Assumptions" }),
    ).toHaveTextContent("The Context agent is reading the brief…");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("says none were recorded once planning has stopped", () => {
    render(<AssumptionsPanel assumptions={[]} status="failed" />);

    expect(
      screen.getByRole("region", { name: "Assumptions" }),
    ).toHaveTextContent("No assumptions were recorded.");
  });
});
