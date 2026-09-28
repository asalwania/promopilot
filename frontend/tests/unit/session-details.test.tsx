import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SessionDetails } from "@/components/session-details";

import {
  approvedSession,
  awaitingApprovalSession,
  awaitingClarificationSession,
  contextAssumptions,
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

  it("shows a plan awaiting approval with the assumptions it rests on", () => {
    render(
      <SessionDetails
        session={{
          ...awaitingApprovalSession,
          assumptions: contextAssumptions,
        }}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent("Awaiting approval");
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();

    // Every request field is an assumption (ADR 0048 D3), so the panel replaces
    // the E3 planning-request summary (ADR 0061).
    const assumptions = screen.getByRole("table", { name: "Assumptions" });
    expect(
      within(assumptions).getByRole("rowheader", { name: "Regions" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "Planning request" }),
    ).not.toBeInTheDocument();

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

  it("asks a session's open questions as a form that sends the answers", async () => {
    const clarify = vi.fn(async () => ({ ok: true as const }));
    render(
      <SessionDetails
        session={awaitingClarificationSession}
        actions={{ clarify }}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent(
      "Awaiting clarification",
    );
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    const form = screen.getByRole("form", { name: "Clarification questions" });
    const [budget, categories] = within(form).getAllByRole("textbox");
    fireEvent.change(budget, { target: { value: "₹2 lakh" } });
    fireEvent.change(categories, { target: { value: "Snacks" } });
    fireEvent.click(
      within(form).getByRole("button", { name: "Answer and resume planning" }),
    );

    await vi.waitFor(() =>
      expect(clarify).toHaveBeenCalledWith({
        marketing_budget: "₹2 lakh",
        "scope.categories": "Snacks",
      }),
    );
    // What the agent read so far stays visible beside the questions.
    expect(
      screen.getByRole("table", { name: "Assumptions" }),
    ).toHaveTextContent("North, West");
  });

  it("asks nothing when no questions are open", () => {
    render(<SessionDetails session={awaitingApprovalSession} />);

    expect(
      screen.queryByRole("form", { name: "Clarification questions" }),
    ).not.toBeInTheDocument();
  });

  it("shows no decision before one is made", () => {
    render(<SessionDetails session={awaitingApprovalSession} />);

    expect(
      screen.queryByText(/was (approved|rejected)/),
    ).not.toBeInTheDocument();
  });
});
