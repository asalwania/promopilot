import { mkdirSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { expect, test, type Locator, type Page } from "@playwright/test";

import { planBrief, PLANNING_MS, sessionScript } from "../e2e/session-scripts";

// The deck's screenshot set (#78, SPEC §17): every key screen at 1920x1080, taken against the
// demo stack. Only the recorded example briefs are planned, so the cassettes answer every
// LLM call and no API key is needed (ADR 0054, ADR 0073). docs/deck.md names each file.
//
// Run: `make screenshots` against a running `make demo`. Output: frontend/screenshots/.
const OUT = process.env.SCREENSHOT_DIR ?? join(__dirname, "../../screenshots");
mkdirSync(OUT, { recursive: true });

// Every file the set must hold; the last test fails the job if one is missing.
const REQUIRED = [
  "01-home-example-briefs",
  "02-clarification-form",
  "03-assumptions-panel",
  "04-live-session-trace",
  "05-plan-region-tabs",
  "06-compare-regions",
  "07-mechanism-drawer",
  "08-line-details-uplift-by-segment",
  "09-constraint-checklist",
  "10-not-selected-list",
  "12-competitor-panel",
  "13-simulation-band-chart",
  "14-simulation-stress-test",
  "15-amend-diff-budget-cut",
  "16-amend-diff-drop-west",
  "17-approve-confirm",
  "18-approved-audit-trail",
  "19-reject-plan",
  "20-infeasibility-panel",
  "21-evals-dashboard",
  "22-evals-scenarios",
  "23-models-registry",
  "24-data-explorer",
];
// 11-cannibalisation-halo-callouts is taken when a recorded plan line carries the callout.

// A viewport screenshot (1920x1080) with `target` scrolled to the top, or the page as it is.
async function shoot(page: Page, name: string, target?: Locator) {
  if (target) {
    await target.evaluate((element) => {
      element.scrollIntoView({ block: "start", inline: "start" });
      window.scrollBy(0, -24);
      // A wide table scrolls its own box sideways: show it from its first column.
      for (let up = element.parentElement; up; up = up.parentElement) {
        up.scrollLeft = 0;
      }
    });
  }
  // Let sticky headers, charts and transitions settle.
  await page.waitForTimeout(400);
  await page.screenshot({ path: join(OUT, `${name}.png`) });
}

// The card (or section) that holds `inner`, so a screenshot starts at its top edge.
function cardOf(inner: Locator): Locator {
  return inner.locator(
    "xpath=ancestor::*[@data-slot='card' or self::section][1]",
  );
}

async function hasPlan(page: Page) {
  await expect(page.getByRole("table", { name: "Plan lines" })).toBeVisible({
    timeout: PLANNING_MS,
  });
}

async function amend(page: Page, text: string) {
  await page.getByRole("textbox", { name: "Amend the brief" }).fill(text);
  await page.getByRole("button", { name: "Amend and re-plan" }).click();
  await expect(page.getByRole("status")).toHaveText("Planning…");
}

// Opens the first plan line that cannibalises other SKUs, if any recorded line does.
async function captureCallouts(page: Page) {
  const row = page
    .getByRole("row")
    .filter({ has: page.getByText("Cannibalisation", { exact: true }) })
    .first();
  if ((await row.count()) === 0) return;
  const details = row.getByRole("button", { name: /^Details for / });
  if ((await details.getAttribute("aria-expanded")) !== "true") {
    await details.click();
  }
  const callout = page
    .getByRole("region", { name: "Cannibalisation", exact: true })
    .first();
  await expect(callout).toBeVisible();
  // Its grandparent is the details grid: both callout columns of the same line.
  await shoot(
    page,
    "11-cannibalisation-halo-callouts",
    callout.locator("xpath=../.."),
  );
}

test("home page with the example briefs and the constraint form", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByRole("status")).toHaveText(/API healthy/);
  await expect(
    page.getByRole("heading", { name: "Try an example" }),
  ).toBeVisible();
  await shoot(page, "01-home-example-briefs");
});

test("the evals, models and data pages", async ({ page }) => {
  await page.goto("/evals");
  const scenarios = page.getByRole("table", { name: "Scenarios" });
  await expect(scenarios).toBeVisible();
  await expect(page.getByLabel("Report provenance")).toContainText(
    "seed-42 world",
  );
  await shoot(page, "21-evals-dashboard");
  await shoot(
    page,
    "22-evals-scenarios",
    page.getByText("Regret distribution", { exact: true }),
  );

  await page.goto("/models");
  await expect(page.getByRole("table").first()).toBeVisible();
  await expect(page.getByText(/^Loading/)).toHaveCount(0);
  await shoot(page, "23-models-registry");

  await page.goto("/data");
  await expect(page.getByRole("table").first()).toBeVisible();
  await expect(page.getByText(/^Loading/)).toHaveCount(0);
  await shoot(page, "24-data-explorer");
});

test("a vague brief: the clarification form", async ({ page }) => {
  test.setTimeout(PLANNING_MS + 60_000);
  const clarify = sessionScript("clarify");
  await page.goto("/");
  await expect(page.getByRole("status")).toHaveText(/API healthy/);
  await page.getByLabel("Brief").fill(clarify.brief);
  await page.getByRole("button", { name: "Plan it" }).click();
  await expect(page).toHaveURL(/\/sessions\/[^/]+$/);
  await expect(page.getByRole("status")).toHaveText("Awaiting clarification", {
    timeout: PLANNING_MS,
  });
  const form = page.getByRole("form", { name: "Clarification questions" });
  await expect(form).toBeVisible();
  await expect(page.getByRole("table", { name: "Assumptions" })).toBeVisible();
  await shoot(page, "02-clarification-form", cardOf(form));
});

test("the infeasibility panel", async ({ page }) => {
  test.setTimeout(PLANNING_MS + 60_000);
  await planBrief(page, sessionScript("infeasible").brief);
  const infeasible = page.getByRole("region", { name: /^Infeasible/ });
  await expect(
    infeasible.getByRole("list", { name: "Binding constraints" }),
  ).toBeVisible();
  await expect(
    infeasible.getByRole("table", { name: "Proposed relaxation" }),
  ).toBeVisible();
  await shoot(page, "20-infeasibility-panel", infeasible);
});

// The `e2e` session: competitor gaps, the simulation band and its stress test, and a rejection.
test("the quick Diwali plan: competitor panel, simulation band, rejection", async ({
  page,
}) => {
  test.setTimeout(PLANNING_MS + 120_000);
  await planBrief(page, sessionScript("e2e").brief);
  await hasPlan(page);

  // F-08: the KVI gaps the planner saw and its response.
  const gaps = page.getByRole("table", { name: "Competitor gaps" });
  await expect(gaps.getByText("Undercut").first()).toBeVisible();
  await shoot(page, "12-competitor-panel", cardOf(gaps));

  // F-09: the P10-P90 band per plan line, then a stress test against a competitor reaction.
  const simulation = page.getByRole("figure", {
    name: "Simulated gross profit by plan line",
  });
  await expect(simulation.locator("svg").first()).toBeVisible();
  await shoot(page, "13-simulation-band-chart", cardOf(simulation));
  await page
    .getByLabel("Competitor match probability")
    .selectOption({ label: "50%" });
  await page.getByRole("button", { name: "Re-simulate" }).click();
  await expect(
    page.getByText(
      "Stress test: the competitor matches each plan line's discount with probability 50%",
      { exact: true },
    ),
  ).toBeVisible({ timeout: 30_000 });
  await shoot(page, "14-simulation-stress-test", cardOf(simulation));

  // F-04 / F-05: a line that cannibalises other SKUs, with its callouts opened.
  await captureCallouts(page);

  // SF-04: rejecting records the reason and keeps the session open.
  const review = page.getByRole("region", { name: "Review plan revision 1" });
  await review.getByRole("button", { name: "Reject plan revision 1" }).click();
  const form = review.getByRole("form", { name: "Reject plan revision 1" });
  await form
    .getByRole("textbox", { name: "Why are you rejecting plan revision 1?" })
    .fill("Too deep on Beverages in West.");
  await shoot(page, "19-reject-plan", review);
  await form.getByRole("button", { name: "Send rejection" }).click();
  await expect(page.getByRole("status")).toHaveText("Rejected");
});

// The `demo` session: the SPEC §3.2 brief, a budget cut, "Drop West", then approval.
test("the Diwali demo: trace, assumptions, plan, amendments and approval", async ({
  page,
}) => {
  test.setTimeout(3 * PLANNING_MS + 120_000);
  const demo = sessionScript("demo");
  const [budgetCut, dropWest] = (demo.steps ?? []).flatMap((step) =>
    step.amend ? [step.amend] : [],
  );
  if (!budgetCut || !dropWest) {
    throw new Error("the demo session no longer has its two amendments");
  }

  // The home page's one-click example fills the recorded brief word for word.
  await page.goto("/");
  await expect(page.getByRole("status")).toHaveText(/API healthy/);
  await page.getByRole("button", { name: /^Try it Diwali demo/ }).click();
  await expect(page.getByLabel("Brief")).toHaveValue(demo.brief);
  await page.getByRole("button", { name: "Plan it" }).click();
  await expect(page).toHaveURL(/\/sessions\/[^/]+$/);

  // SF-01: the trace streams while the planner works (the optimiser takes tens of seconds).
  const trace = page.getByRole("list", { name: "Trace timeline" });
  await expect(
    trace.getByRole("heading", { name: /^Planner/ }).first(),
  ).toBeVisible({ timeout: PLANNING_MS });
  await expect(page.getByRole("status")).toHaveText("Planning…");
  await shoot(page, "04-live-session-trace");

  await expect(page.getByRole("status")).toHaveText("Awaiting approval", {
    timeout: PLANNING_MS,
  });
  await hasPlan(page);

  // AG-01: what the Context agent read or assumed, each with its source and confidence.
  const assumptions = page.getByRole("region", { name: "Assumptions" });
  await expect(assumptions.getByRole("table")).toBeVisible();
  await shoot(page, "03-assumptions-panel", assumptions);

  // F-07: the plan per region; F-01 and F-03: the lines, their details, the segment uplift.
  const regions = page.getByRole("tablist", { name: "Plan regions" });
  await expect(regions.getByRole("tab")).toHaveText([
    /^North/,
    /^West/,
    "Compare regions",
  ]);
  await shoot(page, "05-plan-region-tabs", regions);
  const north = page.getByRole("table", { name: "Plan lines in North" });
  await north
    .getByRole("button", { name: /^Details for / })
    .first()
    .click();
  const uplift = page.getByRole("table", { name: /^Uplift by segment for / });
  await expect(uplift).toBeVisible();
  await shoot(page, "08-line-details-uplift-by-segment", uplift);
  await captureCallouts(page);

  // F-02: the mechanism drawer.
  await north
    .getByRole("button", { name: /^Compare mechanisms for / })
    .first()
    .click();
  const drawer = page.getByRole("dialog", { name: /^Mechanisms for / });
  await expect(
    drawer.getByRole("table", { name: "Mechanism comparison" }),
  ).toBeVisible();
  await shoot(page, "07-mechanism-drawer");
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();

  await regions.getByRole("tab", { name: "Compare regions" }).click();
  await expect(
    page.getByRole("table", { name: "Regions side by side" }),
  ).toBeVisible();
  await shoot(page, "06-compare-regions", regions);

  // F-06 and F-01 AC3: the constraint checklist and the options left out.
  const checklist = page.getByRole("table", { name: "Constraint checklist" });
  await shoot(page, "09-constraint-checklist", cardOf(checklist));
  const notSelected = page.getByRole("region", { name: "Not selected" });
  await expect(notSelected).toBeVisible();
  await shoot(page, "10-not-selected-list", notSelected);

  // AG-05: amend twice; each re-plan shows what changed and why.
  await amend(page, budgetCut);
  const second = page.getByRole("region", { name: "Review plan revision 2" });
  await expect(second).toBeVisible({ timeout: PLANNING_MS });
  const cut = page.getByRole("region", {
    name: "What changed from plan revision 1",
  });
  await expect(cut).toBeVisible();
  await shoot(page, "15-amend-diff-budget-cut", cut);

  await amend(page, dropWest);
  const third = page.getByRole("region", { name: "Review plan revision 3" });
  await expect(third).toBeVisible({ timeout: PLANNING_MS });
  const dropped = page.getByRole("region", {
    name: "What changed from plan revision 2",
  });
  await expect(dropped).toBeVisible();
  await shoot(page, "16-amend-diff-drop-west", dropped);

  // SF-04: approval is a confirmed human decision, then the plan is final with its audit trail.
  await third.getByRole("button", { name: "Approve plan revision 3" }).click();
  await expect(third).toContainText(/Approving makes plan revision 3 final/);
  await shoot(page, "17-approve-confirm", third);
  await third.getByRole("button", { name: "Confirm approval" }).click();
  await expect(page.getByRole("status")).toContainText("Final");
  const trail = page.getByRole("list", { name: "Audit trail" });
  await expect(trail.getByRole("listitem")).toHaveCount(3);
  await shoot(page, "18-approved-audit-trail", cardOf(trail));
});

test("the set is complete", () => {
  const taken = new Set(readdirSync(OUT));
  const missing = REQUIRED.filter((name) => !taken.has(`${name}.png`));
  expect(missing).toEqual([]);
});
