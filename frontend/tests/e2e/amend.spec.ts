import { expect, test, type Page } from "@playwright/test";

import {
  planBrief,
  PLANNING_MS,
  readSession,
  sessionScript,
} from "./session-scripts";

// The recorded `demo` session (ADR 0054): the SPEC §3.2 brief, amended with a budget cut
// and then with "Drop West", and the last revision approved. Its clearance targets are
// within reach, so every revision is feasible (ADR 0086). Each amendment re-plans from
// replayed cassettes. Accepting a relaxation is the `infeasible` journey's.
const demo = sessionScript("demo");
const [budgetCut, dropWest] = (demo.steps ?? []).flatMap((step) =>
  step.amend ? [step.amend] : [],
);
if (!budgetCut || !dropWest) {
  throw new Error("the demo session no longer has its two amendments");
}
if (!demo.steps?.at(-1)?.approve) {
  throw new Error("the demo session no longer approves its last revision");
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

test("amending a plan re-plans it with a diff, and approving makes it final", async ({
  page,
}) => {
  test.setTimeout(3 * PLANNING_MS + 60_000);
  await planBrief(page, demo.brief);

  // The demo reaches its 60% namkeen clearance target, so revision 1 can be approved and
  // its clearance check passes (ADR 0086).
  await expectFeasible(page, 1);
  const clearance = page
    .getByRole("table", { name: "Constraint checklist" })
    .getByRole("row")
    .filter({ has: page.getByRole("rowheader", { name: "Clearance" }) });
  await expect(clearance.getByRole("cell").first()).toHaveText("Pass");

  await amend(page, budgetCut);
  await expect(
    page.getByRole("region", { name: "Review plan revision 2" }),
  ).toBeVisible({ timeout: PLANNING_MS });
  const cut = page.getByRole("region", {
    name: "What changed from plan revision 1",
  });
  await expect(cut).toContainText(`After your amendment “${budgetCut}”`);
  await expect(
    cut.getByRole("list", { name: "Request changes" }),
  ).toContainText(/Marketing budget: .+ → .+/);
  await expect(cut.getByRole("table", { name: "Plan totals" })).toBeVisible();
  await expectFeasible(page, 2);

  await amend(page, dropWest);
  const review = page.getByRole("region", { name: "Review plan revision 3" });
  await expect(review).toBeVisible({ timeout: PLANNING_MS });
  const dropped = page.getByRole("region", {
    name: "What changed from plan revision 2",
  });
  await expect(
    dropped.getByRole("list", { name: "Request changes" }),
  ).toContainText("Regions: North, West → North");
  await expect(
    dropped.getByRole("table", { name: "Removed plan lines" }),
  ).toContainText("West");
  // The new revision opens on its own regions: West is gone.
  await expect(
    page.getByRole("tablist", { name: "Plan regions" }).getByRole("tab"),
  ).toHaveText([/^North/, "Compare regions"]);
  await expectFeasible(page, 3);

  // Revision 3 is feasible, so it is approved, and the session is final.
  await review.getByRole("button", { name: "Approve plan revision 3" }).click();
  await expect(review).toContainText(/Approving makes plan revision 3 final/);
  await review.getByRole("button", { name: "Confirm approval" }).click();
  const status = page.getByRole("status");
  await expect(status).toContainText("Approved");
  await expect(status).toContainText("Final");

  // Both amendments and the approval are on the audit trail, oldest first.
  const trail = page
    .getByRole("list", { name: "Audit trail" })
    .getByRole("listitem");
  await expect(trail).toHaveText([
    new RegExp(`Amended plan revision 1: “${budgetCut}”`),
    new RegExp(`Amended plan revision 2: “${dropWest}”`),
    /Approved plan revision 3$/,
  ]);

  // Every round replayed: the Explainer's recorded answer explains the last revision.
  const session = await readSession<Session>(page);
  expect(session.status).toBe("approved");
  expect(session.amendments.map((amendment) => amendment.text)).toEqual([
    budgetCut,
    dropWest,
  ]);
  expect(session.decisions).toMatchObject([
    { decision: "approved", revision_number: 3 },
  ]);
  expect(session.plan_revision?.number).toBe(3);
  expect(session.plan_revision?.solver_status).not.toBe("INFEASIBLE");
  expect(session.plan_revision?.diff?.from_revision).toBe(2);
  expect(session.plan_revision?.explanation?.source).toBe("llm");
});

// A feasible revision can be approved and shows no infeasibility panel (ADR 0067).
async function expectFeasible(page: Page, revision: number) {
  await expect(
    page
      .getByRole("region", { name: `Review plan revision ${revision}` })
      .getByRole("button", { name: `Approve plan revision ${revision}` }),
  ).toBeEnabled();
  await expect(page.getByRole("region", { name: /^Infeasible/ })).toHaveCount(
    0,
  );
  const session = await readSession<Session>(page);
  expect(session.plan_revision?.number).toBe(revision);
  expect(session.plan_revision?.solver_status).not.toBe("INFEASIBLE");
}

async function amend(page: Page, text: string) {
  await page.getByRole("textbox", { name: "Amend the brief" }).fill(text);
  await page.getByRole("button", { name: "Amend and re-plan" }).click();
  // The 202 shows the session re-planning at once, under the previous revision.
  await expect(page.getByRole("status")).toHaveText("Planning…");
}
