import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SessionDetails } from "@/components/session-details";

import {
  amendedSession,
  approvedAfterAmendmentSession,
  approvedSession,
  awaitingApprovalSession,
  awaitingClarificationSession,
  contextAssumptions,
  failedSession,
  infeasibleSession,
  planLines,
  planningSession,
  rejectedSession,
  replanningSession,
  undercutGaps,
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
      within(screen.getByRole("tablist", { name: "Plan regions" }))
        .getAllByRole("tab")
        .map((tab) => tab.textContent),
    ).toEqual(["North (1)", "West (2)", "Compare regions"]);
    expect(
      within(
        screen.getByRole("table", { name: "Plan lines in North" }),
      ).getAllByRole("row"),
    ).toHaveLength(
      1 + planLines.filter((l) => l.line.region === "North").length,
    );
  });

  it("shows the Explainer's plan summary above the region tabs", () => {
    render(<SessionDetails session={awaitingApprovalSession} />);

    expect(
      screen.getByRole("region", { name: "Plan summary" }),
    ).toHaveTextContent(
      "Two lines across North and West, expected to add ₹12,731 within a ₹2 lakh budget.",
    );
    expect(screen.queryByText("Template explanation")).not.toBeInTheDocument();
  });

  it("says when the plan summary came from the template", () => {
    render(<SessionDetails session={infeasibleSession} />);

    const summary = screen.getByRole("region", { name: "Plan summary" });
    expect(summary).toHaveTextContent("Template explanation");
    expect(summary).toHaveTextContent(
      "Written from a template: the language model was unavailable.",
    );
  });

  it("puts undercut callouts on the lines whose SKU and region are undercut", () => {
    render(
      <SessionDetails
        session={awaitingApprovalSession}
        competitorGaps={undercutGaps}
      />,
    );

    const north = screen.getByRole("table", { name: "Plan lines in North" });
    expect(within(north).getByText("Undercut")).toBeInTheDocument();
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

  it("offers the manager's decision on the revision awaiting approval", async () => {
    const approve = vi.fn(async () => ({ ok: true as const }));
    render(
      <SessionDetails
        session={awaitingApprovalSession}
        actions={{ approve }}
      />,
    );

    const review = screen.getByRole("region", {
      name: "Review plan revision 1",
    });
    fireEvent.click(
      within(review).getByRole("button", { name: "Approve plan revision 1" }),
    );
    fireEvent.click(
      within(review).getByRole("button", { name: "Confirm approval" }),
    );

    await vi.waitFor(() => expect(approve).toHaveBeenCalledWith(1));
  });

  it("sends a rejection's reason and an amendment through the page's actions", async () => {
    const reject = vi.fn(async () => ({ ok: true as const }));
    const amend = vi.fn(async () => ({ ok: true as const }));
    render(
      <SessionDetails
        session={awaitingApprovalSession}
        actions={{ reject, amend }}
      />,
    );

    fireEvent.change(screen.getByRole("textbox", { name: "Amend the brief" }), {
      target: { value: "Drop West" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Amend and re-plan" }));
    await vi.waitFor(() =>
      expect(amend).toHaveBeenCalledWith({ text: "Drop West" }),
    );
    // Once the amendment is sent, the other actions are free again.
    await vi.waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Reject plan revision 1" }),
      ).toBeEnabled(),
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Reject plan revision 1" }),
    );
    fireEvent.change(
      screen.getByRole("textbox", {
        name: "Why are you rejecting plan revision 1?",
      }),
      { target: { value: "Too deep." } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Send rejection" }));
    await vi.waitFor(() => expect(reject).toHaveBeenCalledWith(1, "Too deep."));
  });

  it("keeps a rejected session open for an amendment only", () => {
    render(<SessionDetails session={rejectedSession} />);

    const review = screen.getByRole("region", {
      name: "Review plan revision 1",
    });
    expect(
      within(review).getByRole("form", { name: "Amend the brief" }),
    ).toBeVisible();
    expect(
      within(review).queryByRole("button", { name: /^(Approve|Reject) / }),
    ).not.toBeInTheDocument();
    expect(
      within(screen.getByRole("list", { name: "Audit trail" })).getByRole(
        "listitem",
      ),
    ).toHaveTextContent(
      "Rejected plan revision 1: Too deep on Beverages in West.",
    );
  });

  it("shows an approved session as final and read-only, with its audit trail", () => {
    render(<SessionDetails session={approvedAfterAmendmentSession} />);

    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("Approved");
    expect(status).toHaveTextContent("Final");
    expect(
      screen.getByText(
        "This plan is final: it can no longer be amended, approved or rejected.",
      ),
    ).toBeVisible();
    expect(
      screen.queryByRole("region", { name: /^Review plan revision/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("form", { name: "Amend the brief" }),
    ).not.toBeInTheDocument();
    expect(
      within(screen.getByRole("list", { name: "Audit trail" })).getAllByRole(
        "listitem",
      ),
    ).toHaveLength(3);
  });

  it("offers no decision while planning, awaiting clarification or failed", () => {
    for (const session of [
      planningSession,
      replanningSession,
      awaitingClarificationSession,
      failedSession,
    ]) {
      const { unmount } = render(<SessionDetails session={session} />);
      expect(
        screen.queryByRole("region", { name: /^Review plan revision/ }),
      ).not.toBeInTheDocument();
      unmount();
    }
  });

  it("keeps the previous revision visible under a note while re-planning an amendment", () => {
    render(<SessionDetails session={replanningSession} />);

    expect(screen.getByRole("status")).toHaveTextContent("Planning…");
    expect(
      screen.getByText(
        "Re-planning after your amendment “Budget cut to ₹1.5 lakh”: showing plan revision 1 until the new one is ready.",
      ),
    ).toBeVisible();
    expect(
      screen.getByRole("table", { name: "Plan lines in North" }),
    ).toBeVisible();
  });

  it("shows what changed from the previous revision above the region tabs", () => {
    render(<SessionDetails session={amendedSession} />);

    const diff = screen.getByRole("region", {
      name: "What changed from plan revision 1",
    });
    expect(diff).toHaveTextContent(
      "After your amendment “Budget cut to ₹1.5 lakh”",
    );
    expect(
      within(diff).getByRole("table", { name: "Removed plan lines" }),
    ).toHaveTextContent("SKU0011");
    expect(
      diff.compareDocumentPosition(
        screen.getByRole("tablist", { name: "Plan regions" }),
      ) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("shows no diff for a first revision", () => {
    render(<SessionDetails session={awaitingApprovalSession} />);

    expect(
      screen.queryByRole("region", { name: /^What changed from/ }),
    ).not.toBeInTheDocument();
  });

  it("opens a new revision on its first region, whatever tab the last one showed", () => {
    const { rerender } = render(
      <SessionDetails session={awaitingApprovalSession} />,
    );
    fireEvent.click(screen.getByRole("tab", { name: "Compare regions" }));
    expect(
      screen.getByRole("tab", { name: "Compare regions" }),
    ).toHaveAttribute("aria-selected", "true");

    rerender(<SessionDetails session={amendedSession} />);

    expect(screen.getByRole("tab", { name: /^North/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });
});
