import { readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

type SessionScript = { name: string; brief: string };

// The session scripts `make record-cassettes` recorded: the composed api replays every LLM
// call of the e2e session, so this journey needs no API key (ADR 0019, ADR 0054).
const scripts = JSON.parse(
  readFileSync(
    join(__dirname, "../../../backend/cassettes/sessions.json"),
    "utf-8",
  ),
) as SessionScript[];
const e2e = scripts.find((script) => script.name === "e2e");
if (!e2e) throw new Error("backend/cassettes/sessions.json has no e2e session");

// The planner agent calls the optimiser and the simulator (ADR 0049): on the seed-42 world
// that takes tens of seconds on a CI runner.
const PLANNING_MS = 120_000;

test("a typed brief becomes a plan table with no API key", async ({ page }) => {
  test.setTimeout(PLANNING_MS + 30_000);
  await page.goto("/");
  // Health is fetched in the browser, so seeing it means the page has hydrated
  // and the composer's handlers are attached.
  await expect(page.getByRole("status")).toHaveText(/API healthy/);

  await page.getByLabel("Brief").fill(e2e.brief);
  await page.getByRole("button", { name: "Plan it" }).click();

  await expect(page).toHaveURL(/\/sessions\/[^/]+$/);
  const plan = page.getByRole("table", { name: "Plan lines" });
  await expect(plan).toBeVisible({ timeout: PLANNING_MS });
  await expect(plan.getByRole("row").nth(1)).toBeVisible();

  // The plan is reviewed region by region, every number naming its tool (F-07, ADR 0060).
  const regions = page.getByRole("tablist", { name: "Plan regions" });
  await expect(regions.getByRole("tab")).toHaveText([
    /^North/,
    /^West/,
    "Compare regions",
  ]);
  const north = page.getByRole("table", { name: "Plan lines in North" });
  await expect(north.locator("[title^='Source: ']").first()).toBeVisible();
  await north
    .getByRole("button", { name: /^Details for / })
    .first()
    .click();
  await expect(
    page.getByRole("table", { name: /^Uplift by segment for / }),
  ).toBeVisible();
  await north
    .getByRole("button", { name: /^Compare mechanisms for / })
    .first()
    .click();
  const drawer = page.getByRole("dialog", { name: /^Mechanisms for / });
  await expect(
    drawer.getByRole("table", { name: "Mechanism comparison" }),
  ).toBeVisible();
  await expect(drawer.getByText("Chosen")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await regions.getByRole("tab", { name: /^West/ }).click();
  await expect(
    page.getByRole("table", { name: "Plan lines in West" }),
  ).toBeVisible();
  await regions.getByRole("tab", { name: "Compare regions" }).click();
  await expect(
    page.getByRole("table", { name: "Regions side by side" }),
  ).toBeVisible();

  // The plan is checked constraint by constraint, and the options left out say why
  // (F-01 AC3, ADR 0067).
  const checklist = page.getByRole("table", { name: "Constraint checklist" });
  await expect(checklist.getByRole("rowheader")).toHaveText([
    "Budget",
    "Minimum margin",
    "Stock",
    "Clearance",
    "Policy",
  ]);
  await expect(
    checklist.getByRole("row").nth(1).getByRole("cell").first(),
  ).toHaveText(/^(Pass|Fail)$/);
  await expect(
    page.getByRole("region", { name: "Not selected" }),
  ).toBeVisible();

  // The live trace streamed the agent at work through the proxy (ADR 0047, ADR 0057).
  const trace = page.getByRole("list", { name: "Trace timeline" });
  await expect(
    trace.getByRole("heading", { name: /^Context agent/ }),
  ).toBeVisible();
  await expect(
    trace.getByRole("heading", { name: /^Planner/ }).first(),
  ).toBeVisible();
  await expect(trace.getByText("Arguments and result").first()).toBeVisible();
  // Every Critic run ends by routing the plan: back to the planner, or on (ADR 0051).
  const critic = trace
    .getByRole("listitem")
    .filter({ has: page.getByRole("heading", { name: /^Critic/ }) })
    .first();
  await expect(critic).toContainText(
    /loop_back|plan_valid|cap_reached|infeasible|default_sequence/,
  );

  // The replayed cassettes report their recorded tokens, so planning shows a cost.
  const usage = page.getByRole("region", { name: "LLM usage" });
  await expect(usage.getByRole("definition").first()).toHaveText(/^[1-9]/);

  // The whole graph replayed: the Explainer's recorded answer explains the plan, not the
  // template it falls back to on a cassette miss (ADR 0050 D7).
  const sessionId = new URL(page.url()).pathname.split("/").pop();
  const response = await page.request.get(`/api/sessions/${sessionId}`);
  expect(response.ok()).toBe(true);
  const session = (await response.json()) as {
    plan_revision: { explanation?: { source: string } | null } | null;
  };
  expect(session.plan_revision?.explanation?.source).toBe("llm");
});
