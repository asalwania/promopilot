import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AuditTrail } from "@/components/audit-trail";
import { formatDateTime } from "@/lib/format";

import { approvedAfterAmendmentSession } from "./fixtures/sessions";

const { amendments, decisions } = approvedAfterAmendmentSession;

describe("AuditTrail", () => {
  it("lists every amendment and decision in the order they happened", () => {
    render(<AuditTrail amendments={amendments} decisions={decisions} />);

    const trail = screen.getByRole("list", { name: "Audit trail" });
    const entries = within(trail).getAllByRole("listitem");
    expect(entries.map((entry) => entry.textContent)).toEqual([
      `${formatDateTime("2026-09-28T10:15:00Z")}Rejected plan revision 1: Too deep on Beverages in West.`,
      `${formatDateTime("2026-09-28T10:20:00Z")}Amended plan revision 1: “Budget cut to ₹1.5 lakh”`,
      `${formatDateTime("2026-09-28T10:30:00Z")}Approved plan revision 2`,
    ]);
  });

  it("marks an amendment that accepted the relaxation", () => {
    render(
      <AuditTrail
        amendments={[
          {
            ...amendments[0],
            text: "Accept the smallest relaxation: raise the marketing budget to ₹2,20,000.",
            relaxation: { changes: [], policy_binds: false, proven: true },
          },
        ]}
        decisions={[]}
      />,
    );

    expect(
      within(screen.getByRole("listitem")).getByText("Relaxation accepted"),
    ).toBeVisible();
  });

  it("renders nothing before any amendment or decision", () => {
    const { container } = render(<AuditTrail amendments={[]} decisions={[]} />);

    expect(container).toBeEmptyDOMElement();
  });
});
