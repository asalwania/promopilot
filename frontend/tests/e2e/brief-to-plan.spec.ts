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
