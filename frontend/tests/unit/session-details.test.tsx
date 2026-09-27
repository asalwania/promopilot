import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SessionDetails } from "@/components/session-details";

import {
  awaitingApprovalSession,
  failedSession,
  infeasibleSession,
  planLines,
  planningSession,
} from "./fixtures/sessions";

describe("SessionDetails", () => {
  it("shows a planning session as in progress with its brief", () => {
    render(<SessionDetails session={planningSession} />);

    expect(screen.getByRole("status")).toHaveTextContent("Planning");
    expect(
      screen.getByRole("progressbar", { name: "Planning in progress" }),
    ).toBeInTheDocument();
    expect(screen.getByText(planningSession.brief)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("shows a plan awaiting approval with the planning request it read", () => {
    render(<SessionDetails session={awaitingApprovalSession} />);

    expect(screen.getByRole("status")).toHaveTextContent("Awaiting approval");
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();

    const request = screen.getByRole("region", { name: "Planning request" });
    expect(termsOf(request)).toEqual({
      Regions: "North, West",
      Categories: "Snacks",
      "Promo window": "W105–W108",
      "Marketing budget": "₹2,00,000",
    });

    expect(screen.getByText("Plan revision 1")).toBeInTheDocument();
    expect(
      within(screen.getByRole("table", { name: "Plan lines" })).getAllByRole(
        "row",
      ),
    ).toHaveLength(1 + planLines.length);
  });

  it("shows a failed session with the reason and no spinner", () => {
    render(<SessionDetails session={failedSession} />);

    expect(screen.getByRole("status")).toHaveTextContent("Planning failed");
    expect(screen.getByRole("alert")).toHaveTextContent(
      "The brief could not be planned: the brief states no marketing budget",
    );
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("says an infeasible request is infeasible, not that nothing pays", () => {
    render(<SessionDetails session={infeasibleSession} />);

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Infeasible: no plan reaches every clearance target within the brief's constraints.",
    );
    expect(
      screen.queryByText(
        "No promo option pays for itself within the brief's constraints.",
      ),
    ).not.toBeInTheDocument();
  });

  it("says so when no promo option is worth a plan line", () => {
    render(
      <SessionDetails
        session={{
          ...awaitingApprovalSession,
          plan_revision: {
            number: 1,
            lines: [],
            solver_status: "OPTIMAL",
            objective: 0,
            binding_constraints: [],
            not_selected: [],
            clearance_shortfalls: [],
            policy_findings: [],
          },
        }}
      />,
    );

    expect(
      screen.getByText(
        "No promo option pays for itself within the brief's constraints.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});

function termsOf(element: HTMLElement): Record<string, string | null> {
  const terms = within(element).getAllByRole("term");
  return Object.fromEntries(
    terms.map((term) => [
      term.textContent,
      term.nextElementSibling?.textContent ?? null,
    ]),
  );
}
