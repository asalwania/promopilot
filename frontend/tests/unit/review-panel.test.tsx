import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AmendBox } from "@/components/amend-box";
import { ReviewPanel } from "@/components/review-panel";
import type { PlanRevision } from "@/lib/api/sessions";

import {
  awaitingApprovalSession,
  infeasibleSession,
} from "./fixtures/sessions";

const revision = awaitingApprovalSession.plan_revision as PlanRevision;
const infeasible = infeasibleSession.plan_revision as PlanRevision;

const ok = async () => ({ ok: true as const });

function renderPanel(props: Partial<Parameters<typeof ReviewPanel>[0]> = {}) {
  const handlers = {
    onAmend: vi.fn(ok),
    onApprove: vi.fn(ok),
    onReject: vi.fn(ok),
  };
  render(
    <ReviewPanel
      revision={revision}
      status="awaiting_approval"
      {...handlers}
      {...props}
    />,
  );
  return handlers;
}

function pending() {
  let settle: (outcome: { ok: true }) => void = () => {};
  const promise = new Promise<{ ok: true }>((resolve) => (settle = resolve));
  return { promise, settle };
}

describe("ReviewPanel", () => {
  it("offers approve, reject and amend for a revision awaiting approval", () => {
    renderPanel();

    const panel = screen.getByRole("region", {
      name: "Review plan revision 1",
    });
    expect(
      within(panel).getByRole("button", { name: "Approve plan revision 1" }),
    ).toBeEnabled();
    expect(
      within(panel).getByRole("button", { name: "Reject plan revision 1" }),
    ).toBeEnabled();
    expect(
      within(panel).getByRole("form", { name: "Amend the brief" }),
    ).toBeVisible();
  });

  it("approves only after the manager confirms, naming the revision", async () => {
    const { onApprove } = renderPanel();

    fireEvent.click(
      screen.getByRole("button", { name: "Approve plan revision 1" }),
    );
    expect(onApprove).not.toHaveBeenCalled();
    expect(
      screen.getByText(/Approving makes plan revision 1 final/),
    ).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Confirm approval" }));

    await vi.waitFor(() => expect(onApprove).toHaveBeenCalledWith(1));
  });

  it("goes back without approving on Cancel", () => {
    const { onApprove } = renderPanel();

    fireEvent.click(
      screen.getByRole("button", { name: "Approve plan revision 1" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(
      screen.queryByRole("button", { name: "Confirm approval" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Approve plan revision 1" }),
    ).toBeVisible();
    expect(onApprove).not.toHaveBeenCalled();
  });

  it("shows why an approval failed and lets the manager try again", async () => {
    renderPanel({
      onApprove: vi.fn(async () => ({
        ok: false as const,
        reason: "plan revision 1 is not the session's latest plan revision",
      })),
    });

    fireEvent.click(
      screen.getByRole("button", { name: "Approve plan revision 1" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Confirm approval" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn't approve plan revision 1: plan revision 1 is not the session's latest plan revision",
    );
    expect(
      screen.getByRole("button", { name: "Approve plan revision 1" }),
    ).toBeEnabled();
  });

  it("does not let an infeasible revision be approved, but lets it be rejected", () => {
    renderPanel({ revision: infeasible });

    expect(
      screen.getByRole("button", { name: "Approve plan revision 1" }),
    ).toBeDisabled();
    expect(
      screen.getByText(
        "An infeasible plan can't be approved: amend the brief first.",
      ),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Reject plan revision 1" }),
    ).toBeEnabled();
  });

  it("requires a reason to reject, and sends it trimmed", async () => {
    const { onReject } = renderPanel();

    fireEvent.click(
      screen.getByRole("button", { name: "Reject plan revision 1" }),
    );
    const form = screen.getByRole("form", { name: "Reject plan revision 1" });
    const reason = within(form).getByRole("textbox", {
      name: "Why are you rejecting plan revision 1?",
    });
    expect(reason).toHaveAttribute("maxLength", "2000");

    fireEvent.change(reason, { target: { value: "   " } });
    fireEvent.click(
      within(form).getByRole("button", { name: "Send rejection" }),
    );
    expect(
      await within(form).findByText("Give a reason for rejecting."),
    ).toBeVisible();
    expect(reason).toHaveAttribute("aria-invalid", "true");
    expect(onReject).not.toHaveBeenCalled();

    fireEvent.change(reason, {
      target: { value: "  Too deep on Beverages in West.  " },
    });
    fireEvent.click(
      within(form).getByRole("button", { name: "Send rejection" }),
    );

    await vi.waitFor(() =>
      expect(onReject).toHaveBeenCalledWith(
        1,
        "Too deep on Beverages in West.",
      ),
    );
  });

  it("keeps the reason when a rejection fails", async () => {
    renderPanel({
      onReject: vi.fn(async () => ({
        ok: false as const,
        reason: "HTTP 502",
      })),
    });

    fireEvent.click(
      screen.getByRole("button", { name: "Reject plan revision 1" }),
    );
    const reason = screen.getByRole("textbox", {
      name: "Why are you rejecting plan revision 1?",
    });
    fireEvent.change(reason, { target: { value: "Too deep." } });
    fireEvent.click(screen.getByRole("button", { name: "Send rejection" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn't reject plan revision 1: HTTP 502",
    );
    expect(reason).toHaveValue("Too deep.");
  });

  it("disables every action while one is being sent", async () => {
    const approval = pending();
    renderPanel({ onApprove: vi.fn(() => approval.promise) });

    fireEvent.click(
      screen.getByRole("button", { name: "Approve plan revision 1" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Confirm approval" }));

    await vi.waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Amend and re-plan" }),
      ).toBeDisabled(),
    );
    expect(
      screen.getByRole("button", { name: "Confirm approval" }),
    ).toBeDisabled();
    approval.settle({ ok: true });
  });

  it("offers only an amendment once the revision is rejected", () => {
    renderPanel({ status: "rejected" });

    const panel = screen.getByRole("region", {
      name: "Review plan revision 1",
    });
    expect(panel).toHaveTextContent(
      "Plan revision 1 was rejected. Amend the brief to plan a new revision.",
    );
    expect(
      within(panel).queryByRole("button", { name: /^Approve/ }),
    ).not.toBeInTheDocument();
    expect(
      within(panel).queryByRole("button", { name: /^Reject/ }),
    ).not.toBeInTheDocument();
    expect(
      within(panel).getByRole("form", { name: "Amend the brief" }),
    ).toBeVisible();
  });
});

describe("AmendBox", () => {
  it("sends the amendment trimmed and clears the box once it is accepted", async () => {
    const onAmend = vi.fn(ok);
    render(<AmendBox onAmend={onAmend} />);

    const text = screen.getByRole("textbox", { name: "Amend the brief" });
    expect(text).toHaveAttribute("maxLength", "2000");
    expect(text).toHaveAttribute(
      "placeholder",
      expect.stringContaining("Budget cut to ₹6 lakh"),
    );
    fireEvent.change(text, { target: { value: "  Drop West \n" } });
    fireEvent.click(screen.getByRole("button", { name: "Amend and re-plan" }));

    await vi.waitFor(() =>
      expect(onAmend).toHaveBeenCalledWith({ text: "Drop West" }),
    );
    await vi.waitFor(() => expect(text).toHaveValue(""));
  });

  it("asks for the change instead of sending a blank amendment", async () => {
    const onAmend = vi.fn(ok);
    render(<AmendBox onAmend={onAmend} />);

    fireEvent.change(screen.getByRole("textbox", { name: "Amend the brief" }), {
      target: { value: "  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Amend and re-plan" }));

    expect(await screen.findByText("Write the change you want.")).toBeVisible();
    expect(onAmend).not.toHaveBeenCalled();
  });

  it("keeps the text and shows the API's reason when the amendment fails", async () => {
    render(
      <AmendBox
        onAmend={vi.fn(async () => ({
          ok: false as const,
          reason:
            "the session is approved: only a session awaiting approval, or rejected, can be amended",
        }))}
      />,
    );

    const text = screen.getByRole("textbox", { name: "Amend the brief" });
    fireEvent.change(text, { target: { value: "Drop West" } });
    fireEvent.click(screen.getByRole("button", { name: "Amend and re-plan" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn't amend the brief: the session is approved",
    );
    expect(text).toHaveValue("Drop West");
    expect(
      screen.getByRole("button", { name: "Amend and re-plan" }),
    ).toBeEnabled();
  });

  it("is disabled while another action is being sent", () => {
    render(<AmendBox onAmend={vi.fn(ok)} disabled />);

    expect(
      screen.getByRole("button", { name: "Amend and re-plan" }),
    ).toBeDisabled();
  });
});
