import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ConstraintChecklist } from "@/components/constraint-checklist";
import type { Session } from "@/lib/api/sessions";

import { brokenChecksSession } from "./fixtures/checks";
import {
  awaitingApprovalSession,
  infeasibleSession,
} from "./fixtures/sessions";

function renderChecklist(session: Session) {
  render(
    <ConstraintChecklist
      revision={session.plan_revision!}
      request={session.planning_request}
    />,
  );
}

function rowOf(constraint: string): HTMLElement {
  const table = screen.getByRole("table", { name: "Constraint checklist" });
  return within(table)
    .getByRole("rowheader", { name: constraint })
    .closest("tr")!;
}

function resultOf(constraint: string): string | null {
  return within(rowOf(constraint)).getAllByRole("cell")[0].textContent;
}

describe("ConstraintChecklist", () => {
  it("passes every constraint the plan keeps, with the limit it was checked against", () => {
    renderChecklist(awaitingApprovalSession);

    const panel = screen.getByRole("region", { name: "Constraint checklist" });
    expect(panel).toHaveTextContent("Every constraint passes");
    const table = within(panel).getByRole("table", {
      name: "Constraint checklist",
    });
    expect(
      within(table)
        .getAllByRole("rowheader")
        .map((cell) => cell.textContent),
    ).toEqual(["Budget", "Minimum margin", "Stock", "Clearance", "Policy"]);

    expect(resultOf("Budget")).toBe("Pass");
    expect(rowOf("Budget")).toHaveTextContent(
      "Within the marketing budget of ₹2 lakh",
    );
    expect(within(rowOf("Budget")).getByText("₹2 lakh")).toHaveAttribute(
      "title",
      expect.stringContaining("Source: validate_plan"),
    );
    expect(resultOf("Minimum margin")).toBe("Pass");
    expect(rowOf("Minimum margin")).toHaveTextContent(
      "at or above the company-policy margin floor",
    );
    expect(resultOf("Stock")).toBe("Pass");
    expect(resultOf("Policy")).toBe("Pass");
    expect(rowOf("Policy")).toHaveTextContent(
      "promoted-SKU cap, KVI price tolerance and strong substitutes kept apart.",
    );
    // No target in the brief: nothing to pass or fail.
    expect(resultOf("Clearance")).toBe("Not set");
    expect(rowOf("Clearance")).toHaveTextContent(
      "The brief sets no clearance target.",
    );
  });

  it("fails each constraint the plan still breaks, with validate_plan's findings", () => {
    renderChecklist(brokenChecksSession);

    expect(
      screen.getByRole("region", { name: "Constraint checklist" }),
    ).toHaveTextContent("4 constraints fail");
    expect(resultOf("Budget")).toBe("Fail");
    expect(rowOf("Budget")).toHaveTextContent(
      "total promo cost ₹2,10,000 exceeds the marketing budget ₹2,00,000",
    );
    expect(
      within(rowOf("Budget")).getByText(/total promo cost/),
    ).toHaveAttribute("title", "Source: validate_plan");
    expect(resultOf("Minimum margin")).toBe("Fail");
    expect(rowOf("Minimum margin")).toHaveTextContent(
      "blended expected margin 16.2% is below the minimum margin 18.0%",
    );
    expect(resultOf("Clearance")).toBe("Fail");
    expect(rowOf("Clearance")).toHaveTextContent("short by 3 units");
    expect(resultOf("Policy")).toBe("Fail");
    expect(rowOf("Policy")).toHaveTextContent(
      "effective discount 55% is deeper than the company-policy maximum 50%",
    );
    // A risk finding is no hard constraint: stock still passes.
    expect(resultOf("Stock")).toBe("Pass");
    expect(
      screen.queryByText(/runs out of stock in 24%/),
    ).not.toBeInTheDocument();
  });

  it("fails the Policy row on strong substitutes promoted together", () => {
    const message =
      "SKU0194 and SKU0195 are strong substitutes (estimated θ 0.54, at least 0.35) promoted together in North: promote one of them, or run them in different weeks or segments";
    renderChecklist({
      ...awaitingApprovalSession,
      plan_revision: {
        ...awaitingApprovalSession.plan_revision!,
        open_issues: [
          {
            kind: "violation",
            code: "STRONG_SUBSTITUTES",
            message,
            sku_id: "SKU0194",
            region: "North",
            actual: 0.54,
            limit: 0.35,
          },
        ],
      },
    });

    expect(resultOf("Policy")).toBe("Fail");
    expect(rowOf("Policy")).toHaveTextContent(message);
  });

  it("names the brief's minimum margin and clearance targets when they pass", () => {
    renderChecklist({
      ...brokenChecksSession,
      plan_revision: {
        ...brokenChecksSession.plan_revision!,
        open_issues: [],
        policy_findings: [],
      },
    });

    expect(rowOf("Minimum margin")).toHaveTextContent(
      "at or above the brief's minimum margin of 18%",
    );
    expect(resultOf("Clearance")).toBe("Pass");
    expect(rowOf("Clearance")).toHaveTextContent(
      "Every clearance target is met: SKU0006 at 60% sell-through.",
    );
  });

  it("notes the brief values company policy overrode on the Policy row", () => {
    renderChecklist(brokenChecksSession);

    expect(rowOf("Policy")).toHaveTextContent(
      "Policy kept: the brief's minimum margin of 10.0% is below the company-policy floor of 15.0%; the floor applies",
    );
  });

  it("fails clearance from an infeasible revision's shortfalls", () => {
    renderChecklist(infeasibleSession);

    expect(resultOf("Clearance")).toBe("Fail");
    const clearance = rowOf("Clearance");
    expect(clearance).toHaveTextContent(
      "SKU0029 in North: expected 42% sell-through against a 50% target, 96 units short",
    );
    expect(within(clearance).getByText("96")).toHaveAttribute(
      "title",
      expect.stringContaining("Source: relax_constraints"),
    );
  });
});
