import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { InfeasibilityPanel } from "@/components/infeasibility-panel";

import {
  infeasibleRevision,
  policyBindingRelaxation,
  timedOutRevision,
} from "./fixtures/checks";

const noAccept = vi.fn(async () => ({ ok: true as const }));

function relaxationRows(): HTMLElement[] {
  const table = screen.getByRole("table", { name: "Proposed relaxation" });
  return within(table).getAllByRole("row").slice(1);
}

function cellsOf(row: HTMLElement): (string | null)[] {
  return [
    within(row).getByRole("rowheader").textContent,
    ...within(row)
      .getAllByRole("cell")
      .map((cell) => cell.textContent),
  ];
}

describe("InfeasibilityPanel", () => {
  it("shows why the request is infeasible and the smallest relaxation", () => {
    render(
      <InfeasibilityPanel
        revision={infeasibleRevision}
        canAccept
        onAcceptRelaxation={noAccept}
      />,
    );

    const panel = screen.getByRole("region", { name: /^Infeasible/ });
    expect(within(panel).getByRole("alert")).toHaveTextContent(
      "Infeasible: no plan reaches every clearance target within the brief's constraints.",
    );

    const shortfalls = within(panel).getByRole("table", {
      name: "Clearance shortfalls",
    });
    const shortfall = within(shortfalls).getAllByRole("row")[1];
    expect(shortfall).toHaveTextContent("SKU0029");
    expect(shortfall).toHaveTextContent("North");
    expect(within(shortfall).getByText("50%")).toHaveAttribute(
      "title",
      expect.stringContaining("Source: relax_constraints"),
    );
    expect(shortfall).toHaveTextContent("42%");
    expect(shortfall).toHaveTextContent("96");

    const binding = within(panel).getByRole("list", {
      name: "Binding constraints",
    });
    expect(
      within(binding)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual([
      "Marketing budget: ₹2 lakh (brief)",
      "Clearance target for SKU0029 in North: 50% (brief)",
    ]);

    expect(relaxationRows().map(cellsOf)).toEqual([
      ["Marketing budget", "₹2 lakh", "₹2.15 lakh", "7.2%", "—"],
    ]);
    expect(within(relaxationRows()[0]).getByText("₹2.15 lakh")).toHaveAttribute(
      "title",
      "Source: relax_constraints · exactly ₹2,14,500.00",
    );
    expect(panel).not.toHaveTextContent("Company policy binds");
    expect(panel).not.toHaveTextContent("Not proven smallest");
  });

  it("shows targets lowered or dropped, a tolerance turned off, and when policy binds", () => {
    render(
      <InfeasibilityPanel
        revision={{
          ...infeasibleRevision,
          relaxation: policyBindingRelaxation,
        }}
        canAccept
        onAcceptRelaxation={noAccept}
      />,
    );

    expect(relaxationRows().map(cellsOf)).toEqual([
      ["Clearance target for SKU0006", "60%", "59.93%", "0.1%", "59.93%"],
      ["Marketing budget", "₹2 lakh", "₹2.15 lakh", "7.5%", "—"],
      ["Clearance target for SKU0029", "50%", "Dropped", "100%", "—"],
      ["KVI price tolerance", "3%", "Off", "100%", "—"],
    ]);
    expect(
      screen.getByRole("region", { name: /^Infeasible/ }),
    ).toHaveTextContent(
      "Company policy binds: no change to the budget, caps, minimum margin or KVI price tolerance alone reaches every clearance target, so a target must come down.",
    );
  });

  it("says when the solver ran out of time before proving the request infeasible", () => {
    render(
      <InfeasibilityPanel
        revision={timedOutRevision}
        canAccept
        onAcceptRelaxation={noAccept}
      />,
    );

    const panel = screen.getByRole("region", { name: /^Not proven feasible/ });
    expect(panel).toHaveTextContent(
      "Not proven feasible: the plan misses a clearance target, and the solver ran out of time before settling whether any plan reaches it.",
    );
    expect(panel).toHaveTextContent(
      "Not proven smallest: the solver ran out of time, so a smaller change may exist.",
    );
    expect(
      within(panel).queryByRole("list", { name: "Binding constraints" }),
    ).not.toBeInTheDocument();
  });

  it("triggers an amend that accepts the relaxation in one click", async () => {
    let finish!: (outcome: { ok: true }) => void;
    const accept = vi.fn(
      () => new Promise<{ ok: true }>((resolve) => (finish = resolve)),
    );
    render(
      <InfeasibilityPanel
        revision={infeasibleRevision}
        canAccept
        onAcceptRelaxation={accept}
      />,
    );

    const button = screen.getByRole("button", {
      name: "Accept the relaxation and re-plan",
    });
    fireEvent.click(button);

    expect(accept).toHaveBeenCalledTimes(1);
    expect(
      screen.getByRole("button", { name: "Accepting the relaxation…" }),
    ).toBeDisabled();
    finish({ ok: true });
    expect(
      await screen.findByRole("button", {
        name: "Accept the relaxation and re-plan",
      }),
    ).toBeEnabled();
  });

  it("keeps the button and says why when accepting fails", async () => {
    const accept = vi.fn(async () => ({
      ok: false as const,
      reason: "plan revision 1 has no relaxation to accept",
    }));
    render(
      <InfeasibilityPanel
        revision={infeasibleRevision}
        canAccept
        onAcceptRelaxation={accept}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Accept the relaxation and re-plan" }),
    );

    expect(
      await screen.findByText(
        "Couldn't accept the relaxation: plan revision 1 has no relaxation to accept",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Accept the relaxation and re-plan" }),
    ).toBeEnabled();
  });

  it("names the strong-substitute rule with its θ threshold", () => {
    render(
      <InfeasibilityPanel
        revision={{
          ...infeasibleRevision,
          binding_constraints: [
            {
              kind: "strong_substitutes",
              source: "company_policy",
              limit: 0.35,
              evidence: "infeasible",
              objective_gain: null,
            },
          ],
        }}
        canAccept={false}
        onAcceptRelaxation={noAccept}
      />,
    );

    const binding = screen.getByRole("list", { name: "Binding constraints" });
    expect(within(binding).getByRole("listitem")).toHaveTextContent(
      "Strong substitutes kept apart: θ ≥ 0.35 (company policy)",
    );
  });

  it("offers no button when the session can't be amended", () => {
    render(
      <InfeasibilityPanel
        revision={infeasibleRevision}
        canAccept={false}
        onAcceptRelaxation={noAccept}
      />,
    );

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(
      screen.getByRole("table", { name: "Proposed relaxation" }),
    ).toBeInTheDocument();
  });
});
