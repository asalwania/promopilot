import { expect, test, type Page } from "@playwright/test";

import {
  planBrief,
  PLANNING_MS,
  readSession,
  sessionScript,
} from "./session-scripts";

// The recorded `demo` session (ADR 0054): the SPEC §3.2 brief, amended with a budget cut
// and then with "Drop West", its relaxation accepted and the feasible revision approved
// (ADR 0070). Each amendment re-plans from replayed cassettes.
const demo = sessionScript("demo");
const [budgetCut, dropWest] = (demo.steps ?? []).flatMap((step) =>
  step.amend ? [step.amend] : [],
);
if (!budgetCut || !dropWest) {
  throw new Error("the demo session no longer has its two amendments");
}
if (
  !(demo.steps ?? []).some((step) => step.accept_relaxation) ||
  !demo.steps?.at(-1)?.approve
) {
  throw new Error(
    "the demo session no longer accepts its relaxation and then approves",
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

test("amending a plan re-plans it, accepting its relaxation makes it approvable, and approving makes it final", async ({
  page,
}) => {
  test.setTimeout(4 * PLANNING_MS + 60_000);
  await planBrief(page, demo.brief);

  // The demo's clearance target is out of reach, so its revisions are infeasible: the
  // manager can amend or reject them, but not approve them (ADR 0046 D10).
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
  ).toContainText("Clearance target for SKU0006");
  const relaxation = infeasible.getByRole("table", {
    name: "Proposed relaxation",
  });
  await expect(
    relaxation.getByRole("rowheader", { name: "Clearance target for SKU0006" }),
  ).toBeVisible();
  await expect(
    relaxation.locator("[title^='Source: relax_constraints']").first(),
  ).toBeVisible();
  await expect(
    infeasible.getByRole("button", {
      name: "Accept the relaxation and re-plan",
    }),
  ).toBeEnabled();
  const clearance = page
    .getByRole("table", { name: "Constraint checklist" })
    .getByRole("row")
    .filter({ has: page.getByRole("rowheader", { name: "Clearance" }) });
  await expect(clearance.getByRole("cell").first()).toHaveText("Fail");

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

  await amend(page, dropWest);
  await expect(
    page.getByRole("region", { name: "Review plan revision 3" }),
  ).toBeVisible({ timeout: PLANNING_MS });
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

  // Revision 3 is still infeasible: accepting its relaxation re-plans, one click
  // (ADR 0052 D7, ADR 0067, ADR 0070).
  await expect(
    page
      .getByRole("region", { name: "Review plan revision 3" })
      .getByRole("button", { name: "Approve plan revision 3" }),
  ).toBeDisabled();
  await page
    .getByRole("region", { name: /^Infeasible/ })
    .getByRole("button", { name: "Accept the relaxation and re-plan" })
    .click();
  await expect(page.getByRole("status")).toHaveText("Planning…");
  const review = page.getByRole("region", { name: "Review plan revision 4" });
  await expect(review).toBeVisible({ timeout: PLANNING_MS });
  const relaxed = page.getByRole("region", {
    name: "What changed from plan revision 3",
  });
  await expect(relaxed).toContainText(
    "After your amendment “Accept the smallest relaxation:",
  );
  await expect(
    relaxed.getByRole("list", { name: "Request changes" }),
  ).toContainText(/Clearance targets: .+ → .+/);

  // The relaxed revision is feasible, so it can be approved, and the session is final.
  await review.getByRole("button", { name: "Approve plan revision 4" }).click();
  await expect(review).toContainText(/Approving makes plan revision 4 final/);
  await review.getByRole("button", { name: "Confirm approval" }).click();
  const status = page.getByRole("status");
  await expect(status).toContainText("Approved");
  await expect(status).toContainText("Final");

  // Every amendment, the accepted relaxation among them, and the approval are on the
  // audit trail, oldest first.
  const trail = page
    .getByRole("list", { name: "Audit trail" })
    .getByRole("listitem");
  await expect(trail).toHaveText([
    new RegExp(`Amended plan revision 1: “${budgetCut}”`),
    new RegExp(`Amended plan revision 2: “${dropWest}”`),
    /Amended plan revision 3: “Accept the smallest relaxation: .+”\s*Relaxation accepted/,
    /Approved plan revision 4$/,
  ]);

  // Every round replayed: the Explainer's recorded answer explains the last revision.
  const session = await readSession<Session>(page);
  expect(session.status).toBe("approved");
  expect(session.amendments.map((amendment) => amendment.text)).toEqual([
    budgetCut,
    dropWest,
    expect.stringMatching(/^Accept the smallest relaxation: /),
  ]);
  expect(session.amendments[2]?.relaxation).toBeTruthy();
  expect(session.decisions).toMatchObject([
    { decision: "approved", revision_number: 4 },
  ]);
  expect(session.plan_revision?.number).toBe(4);
  expect(session.plan_revision?.solver_status).not.toBe("INFEASIBLE");
  expect(session.plan_revision?.diff?.from_revision).toBe(3);
  expect(session.plan_revision?.explanation?.source).toBe("llm");
});

async function amend(page: Page, text: string) {
  await page.getByRole("textbox", { name: "Amend the brief" }).fill(text);
  await page.getByRole("button", { name: "Amend and re-plan" }).click();
  // The 202 shows the session re-planning at once, under the previous revision.
  await expect(page.getByRole("status")).toHaveText("Planning…");
}
