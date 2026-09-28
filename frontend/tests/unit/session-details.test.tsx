import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SessionDetails } from "@/components/session-details";

import {
  approvedSession,
  awaitingApprovalSession,
  awaitingClarificationSession,
  failedSession,
  infeasibleSession,
  planLines,
  planningSession,
  rejectedSession,
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

  it("shows what the session's LLM calls used and cost", () => {
    render(<SessionDetails session={awaitingApprovalSession} />);

    const meter = screen.getByRole("region", { name: "LLM usage" });
    expect(meter).toHaveTextContent("45,210");
    expect(meter).toHaveTextContent("₹2.02");
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
            open_issues: [],
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

  it("shows which plan revision an approved session approved", () => {
    render(<SessionDetails session={approvedSession} />);

    expect(screen.getByRole("status")).toHaveTextContent("Approved");
    expect(
      screen.getByText("Plan revision 1 was approved."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("shows why a rejected session's plan revision was rejected", () => {
    render(<SessionDetails session={rejectedSession} />);

    expect(screen.getByRole("status")).toHaveTextContent("Rejected");
    expect(
      screen.getByText(
        "Plan revision 1 was rejected: Too deep on Beverages in West.",
      ),
    ).toBeInTheDocument();
  });

  it("lists the questions a session awaiting clarification asks", () => {
    render(<SessionDetails session={awaitingClarificationSession} />);

    expect(screen.getByRole("status")).toHaveTextContent(
      "Awaiting clarification",
    );
    const questions = screen.getByRole("list", {
      name: "Clarification questions",
    });
    expect(
      within(questions)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual([
      "What marketing budget should the plan's promo cost stay within, in rupees?",
      'Which product categories does "snak stuff" mean? (Snacks?)',
    ]);
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("lists no questions when none are open", () => {
    render(<SessionDetails session={awaitingApprovalSession} />);

    expect(
      screen.queryByRole("list", { name: "Clarification questions" }),
    ).not.toBeInTheDocument();
  });

  it("shows no decision before one is made", () => {
    render(<SessionDetails session={awaitingApprovalSession} />);

    expect(
      screen.queryByText(/was (approved|rejected)/),
    ).not.toBeInTheDocument();
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
