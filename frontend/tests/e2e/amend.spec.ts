import { expect, test, type Page } from "@playwright/test";

import {
  planBrief,
  PLANNING_MS,
  readSession,
  sessionScript,
} from "./session-scripts";

// The recorded `demo` session (ADR 0054): the SPEC §3.2 brief, amended with a budget cut
// and then with "Drop West". Each amendment re-plans from replayed cassettes.
const demo = sessionScript("demo");
const [budgetCut, dropWest] = (demo.steps ?? []).flatMap((step) =>
  step.amend ? [step.amend] : [],
);
if (!budgetCut || !dropWest) {
  throw new Error("the demo session no longer has its two amendments");
}

type Session = {
  amendments: Array<{ text: string }>;
  plan_revision: {
    number: number;
    diff?: { from_revision: number } | null;
    explanation?: { source: string } | null;
  } | null;
};

test("amending a plan re-plans it and shows what changed from the last revision", async ({
  page,
}) => {
  test.setTimeout(3 * PLANNING_MS + 60_000);
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

  // Both amendments are on the audit trail, oldest first.
  await expect(
    page.getByRole("list", { name: "Audit trail" }).getByRole("listitem"),
  ).toHaveText([
    new RegExp(`Amended plan revision 1: “${budgetCut}”`),
    new RegExp(`Amended plan revision 2: “${dropWest}”`),
  ]);

  // Every round replayed: the Explainer's recorded answer explains the last revision.
  const session = await readSession<Session>(page);
  expect(session.amendments.map((amendment) => amendment.text)).toEqual([
    budgetCut,
    dropWest,
  ]);
  expect(session.plan_revision?.number).toBe(3);
  expect(session.plan_revision?.diff?.from_revision).toBe(2);
  expect(session.plan_revision?.explanation?.source).toBe("llm");
});

async function amend(page: Page, text: string) {
  await page.getByRole("textbox", { name: "Amend the brief" }).fill(text);
  await page.getByRole("button", { name: "Amend and re-plan" }).click();
  // The 202 shows the session re-planning at once, under the previous revision.
  await expect(page.getByRole("status")).toHaveText("Planning…");
}
