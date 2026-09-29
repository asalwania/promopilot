import { expect, test } from "@playwright/test";

import {
  planBrief,
  PLANNING_MS,
  readSession,
  sessionScript,
} from "./session-scripts";

// The recorded `e2e` session (ADR 0054): its plan is feasible, so it can be approved.
// Approving makes no LLM call, so it needs no cassette of its own.
const e2e = sessionScript("e2e");

type Session = {
  status: string;
  decisions: Array<{ decision: string; revision_number: number }>;
};

test("approving the plan makes the session final and read-only", async ({
  page,
}) => {
  test.setTimeout(PLANNING_MS + 30_000);
  await planBrief(page, e2e.brief);

  const review = page.getByRole("region", { name: "Review plan revision 1" });
  await review.getByRole("button", { name: "Approve plan revision 1" }).click();
  await expect(review).toContainText(/Approving makes plan revision 1 final/);
  await review.getByRole("button", { name: "Confirm approval" }).click();

  const status = page.getByRole("status");
  await expect(status).toContainText("Approved");
  await expect(status).toContainText("Final");
  await expect(review).toBeHidden();
  await expect(
    page.getByRole("textbox", { name: "Amend the brief" }),
  ).toBeHidden();
  await expect(
    page.getByRole("list", { name: "Audit trail" }).getByRole("listitem"),
  ).toHaveText([/Approved plan revision 1$/]);

  const session = await readSession<Session>(page);
  expect(session.status).toBe("approved");
  expect(session.decisions).toMatchObject([
    { decision: "approved", revision_number: 1 },
  ]);
});
