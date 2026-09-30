import { expect, test } from "@playwright/test";

import {
  planBrief,
  PLANNING_MS,
  readSession,
  sessionScript,
} from "./session-scripts";

// The recorded `infeasible` session (ADR 0086): clearing 95% of the 400g namkeen stock on a
// ₹10k budget is out of reach, so revision 1 is infeasible. Accepting its relaxation
// re-plans a feasible revision 2, which is approved (AG-06, ADR 0070).
const infeasibleScript = sessionScript("infeasible");
const steps = infeasibleScript.steps ?? [];
if (!steps[0]?.accept_relaxation || !steps.at(-1)?.approve) {
  throw new Error(
    "the infeasible session no longer accepts its relaxation and then approves",
  );
}

type Session = {
  status: string;
  amendments: Array<{ text: string; relaxation?: object | null }>;
  decisions: Array<{ decision: string; revision_number: number }>;
  plan_revision: {
    number: number;
    solver_status?: string | null;
    diff?: { from_revision: number } | null;
    explanation?: { source: string } | null;
  } | null;
};

test("an infeasible plan names what binds, and accepting its relaxation makes it approvable", async ({
  page,
}) => {
  test.setTimeout(2 * PLANNING_MS + 60_000);
  await planBrief(page, infeasibleScript.brief);

  // No plan reaches the clearance target, so the revision is infeasible: the manager can
  // amend or reject it, but not approve it (ADR 0046 D10).
  const first = page.getByRole("region", { name: "Review plan revision 1" });
  await expect(
    first.getByRole("button", { name: "Approve plan revision 1" }),
  ).toBeDisabled();
  await expect(
    first.getByText(
      "An infeasible plan can't be approved: amend the brief first.",
    ),
  ).toBeVisible();

  // Why it is infeasible, and the smallest relaxation, one click from an amendment
  // (ADR 0044, ADR 0067).
  const infeasible = page.getByRole("region", { name: /^Infeasible/ });
  await expect(
    infeasible.getByRole("list", { name: "Binding constraints" }),
  ).toContainText(/Clearance target for SKU\d+/);
  const relaxation = infeasible.getByRole("table", {
    name: "Proposed relaxation",
  });
  await expect(
    relaxation
      .getByRole("rowheader", { name: /^Clearance target for SKU\d+/ })
      .first(),
  ).toBeVisible();
  await expect(
    relaxation.locator("[title^='Source: relax_constraints']").first(),
  ).toBeVisible();
  const clearance = page
    .getByRole("table", { name: "Constraint checklist" })
    .getByRole("row")
    .filter({ has: page.getByRole("rowheader", { name: "Clearance" }) });
  await expect(clearance.getByRole("cell").first()).toHaveText("Fail");

  // Accepting the relaxation re-plans, one click (ADR 0052 D7, ADR 0067, ADR 0070).
  await infeasible
    .getByRole("button", { name: "Accept the relaxation and re-plan" })
    .click();
  await expect(page.getByRole("status")).toHaveText("Planning…");
  const review = page.getByRole("region", { name: "Review plan revision 2" });
  await expect(review).toBeVisible({ timeout: PLANNING_MS });
  const relaxed = page.getByRole("region", {
    name: "What changed from plan revision 1",
  });
  await expect(relaxed).toContainText(
    "After your amendment “Accept the smallest relaxation:",
  );
  await expect(
    relaxed.getByRole("list", { name: "Request changes" }),
  ).toContainText(/Clearance targets: .+ → .+/);

  // The relaxed revision is feasible, so it can be approved, and the session is final.
  await review.getByRole("button", { name: "Approve plan revision 2" }).click();
  await expect(review).toContainText(/Approving makes plan revision 2 final/);
  await review.getByRole("button", { name: "Confirm approval" }).click();
  const status = page.getByRole("status");
  await expect(status).toContainText("Approved");
  await expect(status).toContainText("Final");

  // The accepted relaxation (badged) and the approval are on the audit trail.
  const trail = page
    .getByRole("list", { name: "Audit trail" })
    .getByRole("listitem");
  await expect(trail).toHaveText([
    /Amended plan revision 1: “Accept the smallest relaxation: .+”\s*Relaxation accepted/,
    /Approved plan revision 2$/,
  ]);

  // Every round replayed: the Explainer's recorded answer explains the relaxed revision.
  const session = await readSession<Session>(page);
  expect(session.status).toBe("approved");
  expect(session.amendments.map((amendment) => amendment.text)).toEqual([
    expect.stringMatching(/^Accept the smallest relaxation: /),
  ]);
  expect(session.amendments[0]?.relaxation).toBeTruthy();
  expect(session.decisions).toMatchObject([
    { decision: "approved", revision_number: 2 },
  ]);
  expect(session.plan_revision?.number).toBe(2);
  expect(session.plan_revision?.solver_status).not.toBe("INFEASIBLE");
  expect(session.plan_revision?.diff?.from_revision).toBe(1);
  expect(session.plan_revision?.explanation?.source).toBe("llm");
});
