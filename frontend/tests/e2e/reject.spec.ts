import { expect, test } from "@playwright/test";

import {
  planBrief,
  PLANNING_MS,
  readSession,
  sessionScript,
} from "./session-scripts";

// The recorded `e2e` session (ADR 0054), rejected. Rejecting makes no LLM call, so it
// needs no cassette of its own.
const e2e = sessionScript("e2e");
const REASON = "Too deep on Beverages in West.";

type Session = {
  status: string;
  decisions: Array<{
    decision: string;
    revision_number: number;
    reason?: string | null;
  }>;
};

test("rejecting the plan records the reason and keeps the session open", async ({
  page,
}) => {
  test.setTimeout(PLANNING_MS + 30_000);
  await planBrief(page, e2e.brief);

  const review = page.getByRole("region", { name: "Review plan revision 1" });
  await review.getByRole("button", { name: "Reject plan revision 1" }).click();
  const form = review.getByRole("form", { name: "Reject plan revision 1" });
  await form.getByRole("button", { name: "Send rejection" }).click();
  await expect(form.getByText("Give a reason for rejecting.")).toBeVisible();

  await form
    .getByRole("textbox", { name: "Why are you rejecting plan revision 1?" })
    .fill(REASON);
  await form.getByRole("button", { name: "Send rejection" }).click();

  await expect(page.getByRole("status")).toHaveText("Rejected");
  await expect(
    page.getByText(`Plan revision 1 was rejected: ${REASON}`),
  ).toBeVisible();
  // Still open: the manager can amend the brief, but not decide on this revision again.
  await expect(
    review.getByRole("form", { name: "Amend the brief" }),
  ).toBeVisible();
  await expect(
    review.getByRole("button", { name: /^(Approve|Reject) plan revision/ }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("list", { name: "Audit trail" }).getByRole("listitem"),
  ).toHaveText([new RegExp(`Rejected plan revision 1: ${REASON}$`)]);

  const session = await readSession<Session>(page);
  expect(session.status).toBe("rejected");
  expect(session.decisions).toMatchObject([
    { decision: "rejected", revision_number: 1, reason: REASON },
  ]);
});
