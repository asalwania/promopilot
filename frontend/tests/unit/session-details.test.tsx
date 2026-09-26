import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SessionDetails } from "@/components/session-details";

import {
  awaitingApprovalSession,
  failedSession,
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

  it("says so when no plan line fits the budget", () => {
    render(
      <SessionDetails
        session={{
          ...awaitingApprovalSession,
          plan_revision: { number: 1, lines: [] },
        }}
      />,
    );

    expect(
      screen.getByText("No plan line fits within the marketing budget."),
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
