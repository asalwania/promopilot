import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SimulationPanel } from "@/components/simulation-panel";
import type { PlanSimulation } from "@/lib/api/sessions";

import { awaitingApprovalSession } from "./fixtures/sessions";

const simulation = awaitingApprovalSession.plan_revision!
  .simulation as PlanSimulation;
const stressed: PlanSimulation = {
  ...simulation,
  competitor_reaction: { match_probability: 0.5 },
};

const ok = async () => ({ ok: true as const });

function renderPanel(
  props: Partial<Parameters<typeof SimulationPanel>[0]> = {},
) {
  return render(
    <SimulationPanel revisionNumber={1} simulation={simulation} {...props} />,
  );
}

function valuesTable() {
  fireEvent.click(screen.getByRole("button", { name: "Show values" }));
  return screen.getByRole("table", { name: "Simulated ranges" });
}

function rowTexts(table: HTMLElement) {
  return within(table)
    .getAllByRole("row")
    .slice(1)
    .map((row) =>
      within(row)
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
    );
}

// The first chart pays for loading Recharts, which can outlast the default under load.
describe("SimulationPanel", { timeout: 15_000 }, () => {
  it("charts each plan line's P10–P90 band and P50 from the simulation", () => {
    renderPanel();

    const chart = screen.getByRole("figure", {
      name: "Simulated gross profit by plan line",
    });
    const legend = within(chart).getByRole("list", { name: "Legend" });
    expect(
      within(legend)
        .getAllByRole("listitem")
        .map((i) => i.textContent),
    ).toEqual(["P10–P90 band", "P50"]);
    expect(rowTexts(valuesTable())).toEqual([
      ["SKU0003 · North", "₹11,200", "₹12,960", "₹13,280"],
      ["SKU0011 · West", "₹22,400", "₹24,608", "₹27,040"],
      ["SKU0003 · West", "₹3,500", "₹4,180", "₹4,700"],
    ]);
  });

  it("names the simulator and its runs on every charted value", () => {
    renderPanel();

    const [p10] = within(valuesTable()).getAllByTitle(/^Source: /);
    expect(p10).toHaveAttribute(
      "title",
      "Source: simulate_plan · gross profit, P10 of 1000 runs (seed 0): ₹11,200",
    );
  });

  it("switches the charted metric", () => {
    renderPanel();

    fireEvent.click(screen.getByRole("button", { name: "Units" }));

    expect(
      screen.getByRole("figure", { name: "Simulated units by plan line" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Units" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(rowTexts(valuesTable())[0]).toEqual([
      "SKU0003 · North",
      "700",
      "810",
      "830",
    ]);
  });

  it("charts one region's lines at a time when asked", () => {
    renderPanel();

    fireEvent.click(screen.getByRole("button", { name: "West" }));

    expect(rowTexts(valuesTable()).map(([line]) => line)).toEqual([
      "SKU0011 · West",
      "SKU0003 · West",
    ]);
  });

  it("shows the plan's totals and each region's stock-out risk", () => {
    renderPanel();

    const totals = screen.getByRole("region", { name: "Plan totals" });
    const profit = within(totals).getByText("Gross profit")
      .parentElement as HTMLElement;
    expect(profit).toHaveTextContent("₹37,568");
    expect(profit).toHaveTextContent("P10 ₹34,400 – P90 ₹40,000");
    expect(within(profit).getByText("₹37,568")).toHaveAttribute(
      "title",
      "Source: simulate_plan · gross profit, P50 of 1000 runs (seed 0): ₹37,568",
    );
    expect(
      within(totals).getByText("Stock-out risk in North").parentElement,
    ).toHaveTextContent("31%");
  });

  it("labels a plain simulation and a stress test by their competitor reaction", () => {
    const { rerender } = renderPanel();
    expect(screen.getByText("No competitor reaction")).toBeInTheDocument();

    rerender(<SimulationPanel revisionNumber={1} simulation={stressed} />);

    expect(
      screen.getByText(
        "Stress test: the competitor matches each plan line's discount with probability 50%",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/scenario/i)).not.toBeInTheDocument();
  });

  it("re-simulates with the chosen competitor match probability", async () => {
    const onSimulate = vi.fn(ok);
    renderPanel({ onSimulate });

    const probability = screen.getByLabelText("Competitor match probability");
    expect(probability).toHaveValue("0.5");
    fireEvent.click(screen.getByRole("button", { name: "Re-simulate" }));
    await screen.findByRole("button", { name: "Re-simulate" });
    expect(onSimulate).toHaveBeenLastCalledWith(0.5);

    fireEvent.change(probability, { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "Re-simulate" }));
    await screen.findByRole("button", { name: "Re-simulate" });
    expect(onSimulate).toHaveBeenLastCalledWith(1);
  });

  it("re-simulates without a competitor reaction", async () => {
    const onSimulate = vi.fn(ok);
    renderPanel({ onSimulate });

    fireEvent.change(screen.getByLabelText("Competitor match probability"), {
      target: { value: "none" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Re-simulate" }));

    await screen.findByRole("button", { name: "Re-simulate" });
    expect(onSimulate).toHaveBeenCalledWith(null);
  });

  it("disables the control while the simulation runs", async () => {
    let finish: (value: { ok: true }) => void = () => {};
    const onSimulate = vi.fn(
      () => new Promise<{ ok: true }>((resolve) => (finish = resolve)),
    );
    renderPanel({ onSimulate });

    fireEvent.click(screen.getByRole("button", { name: "Re-simulate" }));

    const running = screen.getByRole("button", { name: "Re-simulating…" });
    expect(running).toBeDisabled();
    expect(
      screen.getByLabelText("Competitor match probability"),
    ).toBeDisabled();
    finish({ ok: true });
    expect(
      await screen.findByRole("button", { name: "Re-simulate" }),
    ).toBeEnabled();
  });

  it("says why a re-simulation failed", async () => {
    const onSimulate = vi.fn(async () => ({
      ok: false as const,
      reason: "plan revision 1 is approved and final",
    }));
    renderPanel({ onSimulate });

    fireEvent.click(screen.getByRole("button", { name: "Re-simulate" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn't re-simulate: plan revision 1 is approved and final",
    );
  });

  it("offers no re-simulation without a handler, as on a final plan", () => {
    renderPanel();

    expect(
      screen.queryByRole("button", { name: "Re-simulate" }),
    ).not.toBeInTheDocument();
  });

  it("says when the revision has no simulation, and can still simulate it", () => {
    renderPanel({ simulation: null, onSimulate: vi.fn(ok) });

    expect(
      screen.getByText("Plan revision 1 has no simulation yet."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("figure")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Re-simulate" }),
    ).toBeInTheDocument();
  });
});
