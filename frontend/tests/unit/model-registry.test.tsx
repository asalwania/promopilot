import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ModelRegistry } from "@/components/model-registry";

import { demandV1, demandV2, relationsV1 } from "./fixtures/models";

function rowsOf(table: HTMLElement) {
  return within(table)
    .getAllByRole("row")
    .map((row) =>
      within(row)
        .queryAllByRole("cell")
        .map((cell) => cell.textContent),
    )
    .filter((cells) => cells.length > 0);
}

describe("ModelRegistry", () => {
  it("shows one table per kind with a row per version, newest first", () => {
    render(<ModelRegistry models={[relationsV1, demandV2, demandV1]} />);

    expect(
      screen.getByRole("heading", { name: "Demand model" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Relations model" }),
    ).toBeInTheDocument();
    const demand = screen.getByRole("table", { name: "Demand model versions" });
    const rows = rowsOf(demand);
    expect(rows.map((row) => row[0])).toEqual(["v2", "v1"]);
    expect(rows[0][1]).toBe("Live");
    expect(rows[1][1]).toBe("");
    expect(rows[0][2]).toMatch(/26 Sept 2026/);
    expect(rows[0][3]).toBe("W105");
  });

  it("labels known metrics readably and formats them by unit", () => {
    render(<ModelRegistry models={[demandV2, demandV1]} />);

    const demand = screen.getByRole("table", { name: "Demand model versions" });
    const headers = within(demand)
      .getAllByRole("columnheader")
      .map((header) => header.textContent);
    expect(headers).toEqual([
      "Version",
      "Status",
      "Trained",
      "As-of week",
      "WAPE, store × SKU × segment",
      "WAPE, store × SKU",
      "WAPE, region × SKU",
      "SKUs with a fitted response",
      "Median elasticity std. error",
    ]);
    const [latest, older] = rowsOf(demand);
    expect(latest.slice(4)).toEqual([
      "44.1%",
      "25.1%",
      "14.1%",
      "118",
      "0.087",
    ]);
    expect(older.slice(4)).toEqual(["45.0%", "—", "—", "—", "—"]);
  });

  it("shows an unknown metric under its raw name to 3 decimals", () => {
    render(
      <ModelRegistry
        models={[{ ...relationsV1, metrics: { pair_recall: 0.83333 } }]}
      />,
    );

    const relations = screen.getByRole("table", {
      name: "Relations model versions",
    });
    expect(
      within(relations).getByRole("columnheader", { name: "pair_recall" }),
    ).toBeInTheDocument();
    expect(rowsOf(relations)[0][4]).toBe("0.833");
  });

  it("says when no model is registered", () => {
    render(<ModelRegistry models={[]} />);

    expect(screen.getByText(/No model is registered yet/)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
